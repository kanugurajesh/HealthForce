"""GroqProvider (gpt-oss-120b) with a fake client: request shape, strict schema, error mapping,
and that its output is still grounded by the pipeline. No network or API key needed."""

import json
from types import SimpleNamespace
from typing import Any

import groq
import httpx
import pytest

from app.config import get_settings
from app.extraction.errors import ExtractionError
from app.extraction.providers import SYSTEM_PROMPT, GroqProvider
from app.extraction.schemas import ExtractionOutput, strict_json_schema
from app.services.processing import run_now

DOC = "Riley Shaw\nLICENSES & CERTIFICATIONS\n- BLS Provider, exp. 04/2027\n"


def output(**overrides: Any) -> dict[str, Any]:
    base = {
        "candidate_name": "Riley Shaw",
        "document_type": "resume",
        "summary": None,
        "experiences": [],
        "qualifications": [],
        "skills": [],
        "credentials": [
            {
                "name": "BLS Provider",
                "evidence_quote": "BLS Provider, exp. 04/2027",
                "issuer": None,
                "identifier": None,
                "jurisdiction": None,
                "issue_date_text": None,
                "expiration_date_text": "04/2027",
            }
        ],
        "extraction_notes": [],
    }
    return {**base, **overrides}


class FakeCompletions:
    def __init__(self, content: str | None = None, finish_reason: str = "stop", error: Exception | None = None) -> None:
        self.content, self.finish_reason, self.error = content, finish_reason, error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        message = SimpleNamespace(content=self.content)
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=self.finish_reason)], usage=usage)


def fake_client(**kw: Any) -> tuple[Any, FakeCompletions]:
    completions = FakeCompletions(**kw)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def api_error(cls: type[Exception], status: int, body: Any = None) -> Exception:
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))
    return cls("error", response=response, body=body)  # type: ignore[call-arg]


# ----------------------------------------------------------------- schema


def _objects(schema: Any):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for v in schema.values():
            yield from _objects(v)
    elif isinstance(schema, list):
        for v in schema:
            yield from _objects(v)


def test_schema_satisfies_groq_strict_mode_rules():
    schema = strict_json_schema()
    objects = list(_objects(schema))
    assert len(objects) == 5  # root + 4 item types
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    creds = schema["properties"]["credentials"]["items"]["properties"]
    assert creds["expiration_date_text"]["type"] == ["string", "null"]
    assert creds["evidence_quote"]["type"] == "string"
    assert schema["properties"]["document_type"]["enum"] == ["resume", "credential", "other"]
    # No status / verification / score field exists for a model to fill.
    assert not {"status", "verified", "verification_status", "score"} & set(creds)


def test_schema_matches_pydantic_model_fields():
    assert set(strict_json_schema()["properties"]) == set(ExtractionOutput.model_fields)


# ----------------------------------------------------------------- request & success


def test_request_shape_and_success():
    client, completions = fake_client(content=json.dumps(output()))
    result = GroqProvider(client=client).extract(DOC, "resume")
    assert result["credentials"][0]["name"] == "BLS Provider"

    call = completions.calls[0]
    assert call["model"] == get_settings().groq_model == "openai/gpt-oss-120b"
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["response_format"]["json_schema"]["schema"] == strict_json_schema()
    assert call["include_reasoning"] is False
    assert call["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    user = call["messages"][1]["content"]
    assert "<untrusted_document id=" in user and DOC in user


# ----------------------------------------------------------------- failures


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (api_error(groq.RateLimitError, 429), "provider_unavailable", True),
        (api_error(groq.InternalServerError, 503), "provider_unavailable", True),
        (api_error(groq.AuthenticationError, 401), "provider_auth", False),
        (api_error(groq.PermissionDeniedError, 403), "provider_auth", False),
        (api_error(groq.BadRequestError, 400, {"error": {"code": "json_validate_failed", "message": "x"}}), "provider_invalid_output", True),
        (api_error(groq.BadRequestError, 400, {"error": {"code": "context_length_exceeded"}}), "provider_rejected_request", False),
        (api_error(groq.APIStatusError, 413), "document_too_long", False),
        (groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com")), "provider_unavailable", True),
    ],
)
def test_errors_are_classified(error, code, retryable):
    client, _ = fake_client(error=error)
    with pytest.raises(ExtractionError) as e:
        GroqProvider(client=client).extract(DOC, "resume")
    assert (e.value.code, e.value.retryable) == (code, retryable)


@pytest.mark.parametrize(
    ("content", "finish", "code", "retryable"),
    [
        ("{not json", "stop", "provider_invalid_output", True),
        ('["a", "list"]', "stop", "provider_invalid_output", True),
        ("", "stop", "provider_invalid_output", True),
        (json.dumps(output()), "length", "provider_truncated", False),
        (json.dumps(output()), "content_filter", "provider_refused", False),
    ],
)
def test_bad_completions_are_classified(content, finish, code, retryable):
    client, _ = fake_client(content=content, finish_reason=finish)
    with pytest.raises(ExtractionError) as e:
        GroqProvider(client=client).extract(DOC, "resume")
    assert (e.value.code, e.value.retryable) == (code, retryable)


def test_missing_api_key_fails_clearly(monkeypatch):
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    with pytest.raises(ExtractionError) as e:
        GroqProvider()
    assert e.value.code == "provider_not_configured" and not e.value.retryable


# ----------------------------------------------------------------- end to end through the pipeline


def test_job_fails_permanently_when_groq_selected_without_key(world, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "extraction_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", None)
    cid = world.recruiter.ok("post", "/api/candidates", json={"full_name": "Riley Shaw"})["id"]
    doc = world.recruiter.upload(cid, "r.txt", DOC, process=False)
    assert run_now(doc["job"]["id"]) == "failed"
    job = world.recruiter.ok("get", f"/api/documents/{doc['id']}")["job"]
    assert job["error_code"] == "provider_not_configured" and "GROQ_API_KEY" in job["last_error"]


def test_model_output_is_grounded_like_any_provider(world):
    """A hallucinated expiration date and an invented credential from the model never reach the database."""
    hallucinated = output(
        credentials=[
            {
                "name": "BLS Provider",
                "evidence_quote": "BLS Provider, exp. 04/2027",
                "issuer": "American Heart Association",
                "identifier": None,
                "jurisdiction": None,
                "issue_date_text": None,
                "expiration_date_text": "04/2029",
            },
            {
                "name": "ACLS Provider",
                "evidence_quote": "ACLS Provider, exp. 05/2028",
                "issuer": None,
                "identifier": None,
                "jurisdiction": None,
                "issue_date_text": None,
                "expiration_date_text": "05/2028",
            },
        ]
    )
    client, _ = fake_client(content=json.dumps(hallucinated))
    cid = world.recruiter.ok("post", "/api/candidates", json={"full_name": "Riley Shaw"})["id"]
    doc = world.recruiter.upload(cid, "r.txt", DOC, process=False)
    assert run_now(doc["job"]["id"], GroqProvider(client=client)) == "succeeded"
    d = world.recruiter.ok("get", f"/api/documents/{doc['id']}")
    assert d["job"]["provider"] == "groq"
    creds = d["credentials"]
    assert [c["type_code"] for c in creds] == ["BLS"]  # invented ACLS dropped
    assert creds[0]["source"] == "ai"
    assert creds[0]["expiration_date"] is None and creds[0]["issuer"] is None  # unsupported values discarded
    assert any("not found in the document" in f for f in creds[0]["flags"])
