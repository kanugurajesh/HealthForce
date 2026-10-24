"""Job lifecycle: retries, permanent failures, idempotency, reprocessing, stale leases."""

from datetime import timedelta
from typing import Any

from app.db import SessionLocal, utcnow
from app.domain import ClaimSource
from app.extraction.errors import ExtractionError
from app.extraction.providers import MockProvider
from app.models import ProcessingJob
from app.services.processing import claim, process_job, reclaim_stale, run_now

RESUME = """Sam Patel
EXPERIENCE
Staff Nurse, Medical ICU — Riverside General Hospital, Columbus, OH | 06/2020 – Present
LICENSES & CERTIFICATIONS
- BLS Provider, exp. 04/2027
SKILLS
Telemetry, Epic EHR
"""


class FlakyProvider:
    """Fails with a transient error `failures` times, then behaves like the mock provider."""

    name = "flaky"
    source = ClaimSource.MOCK

    def __init__(self, failures: int, retryable: bool = True) -> None:
        self.failures, self.retryable, self.calls = failures, retryable, 0

    def extract(self, text: str, kind_hint: str) -> Any:
        self.calls += 1
        if self.calls <= self.failures:
            raise ExtractionError("provider_unavailable", "The AI provider is temporarily unavailable.", retryable=self.retryable)
        return MockProvider().extract(text, kind_hint)


class GarbageProvider:
    name = "garbage"
    source = ClaimSource.AI

    def extract(self, text: str, kind_hint: str) -> Any:
        return "I'm sorry, here is the data you asked for"


def new_candidate(world, name="Sam Patel") -> str:
    return world.recruiter.ok("post", "/api/candidates", json={"full_name": name})["id"]


def job_row(job_id: str) -> ProcessingJob:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        db.expunge(job)
        return job


def make_due(job_id: str) -> None:
    with SessionLocal() as db:
        db.get(ProcessingJob, job_id).next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()


def test_transient_failure_is_retried_with_backoff_then_succeeds(world):
    cid = new_candidate(world)
    doc = world.recruiter.upload(cid, "r.txt", RESUME, process=False)
    job_id = doc["job"]["id"]
    flaky = FlakyProvider(failures=1)

    assert run_now(job_id, flaky) == "pending"
    job = job_row(job_id)
    assert job.attempts == 1 and job.error_code == "provider_unavailable" and job.next_attempt_at > utcnow()
    assert run_now(job_id, flaky) == "pending"  # not due yet: backoff is respected
    assert flaky.calls == 1

    make_due(job_id)
    assert run_now(job_id, flaky) == "succeeded"
    job = job_row(job_id)
    assert job.attempts == 2 and job.error_code is None and job.stats["claims"]["credential"] == 1


def test_retries_are_bounded_then_job_fails_visibly(world):
    cid = new_candidate(world)
    job_id = world.recruiter.upload(cid, "r.txt", RESUME, process=False)["job"]["id"]
    flaky = FlakyProvider(failures=99)
    for _ in range(3):
        make_due(job_id)
        run_now(job_id, flaky)
    job = job_row(job_id)
    assert job.status == "failed" and job.attempts == job.max_attempts == 3
    assert flaky.calls == 3
    events = world.recruiter.ok("get", f"/api/candidates/{cid}/activity")
    assert any(e["action"] == "document.processing_failed" for e in events)
    detail = world.recruiter.candidate(cid)
    assert detail["next_actions"][0]["label"].startswith("Processing failed")


def test_permanent_failure_is_not_retried(world):
    cid = new_candidate(world)
    job_id = world.recruiter.upload(cid, "r.txt", RESUME, process=False)["job"]["id"]
    assert run_now(job_id, FlakyProvider(failures=5, retryable=False)) == "failed"
    assert job_row(job_id).attempts == 1


def test_malformed_provider_output_fails_the_attempt_without_partial_data(world):
    cid = new_candidate(world)
    job_id = world.recruiter.upload(cid, "r.txt", RESUME, process=False)["job"]["id"]
    assert run_now(job_id, GarbageProvider()) == "pending"  # retryable
    assert job_row(job_id).error_code == "provider_invalid_output"
    assert world.recruiter.candidate(cid)["credentials"] == []


def test_manual_retry_of_failed_job(world):
    cid = new_candidate(world)
    doc = world.recruiter.upload(cid, "r.txt", RESUME, process=False)
    job_id = doc["job"]["id"]
    run_now(job_id, FlakyProvider(failures=5, retryable=False))
    assert job_row(job_id).status == "failed"

    out = world.recruiter.ok("post", f"/api/documents/{doc['id']}/process", status=202)
    assert out["job"]["status"] == "pending" and out["job"]["attempts"] == 0
    # Repeating the request while queued is a no-op (idempotent).
    again = world.recruiter.ok("post", f"/api/documents/{doc['id']}/process", status=202)
    assert again["job"]["id"] == job_id and again["job"]["status"] == "pending"
    assert run_now(job_id) == "succeeded"


def test_duplicate_delivery_of_a_job_is_a_no_op(world):
    cid = new_candidate(world)
    job_id = world.recruiter.upload(cid, "r.txt", RESUME, process=False)["job"]["id"]
    with SessionLocal() as db:
        assert claim(db, job_id) == job_id
        assert claim(db, job_id) is None  # second worker cannot claim it
    assert process_job(job_id) == "succeeded"
    assert process_job(job_id) == "succeeded"  # redelivery: untouched
    detail = world.recruiter.candidate(cid)
    assert len(detail["credentials"]) == 1 and len(detail["experiences"]) == 1


def test_duplicate_upload_returns_existing_document(world):
    cid = new_candidate(world)
    first = world.recruiter.client.post(f"/api/candidates/{cid}/documents", files={"file": ("r.txt", RESUME.encode(), "text/plain")}, data={"kind": "resume"})
    second = world.recruiter.client.post(
        f"/api/candidates/{cid}/documents", files={"file": ("copy.txt", RESUME.encode(), "text/plain")}, data={"kind": "resume"}
    )
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["created"] is False and second.json()["document"]["id"] == first.json()["document"]["id"]
    assert len(world.recruiter.candidate(cid)["documents"]) == 1


def test_reprocessing_preserves_human_reviewed_claims(world):
    cid = new_candidate(world)
    doc = world.recruiter.upload(cid, "r.txt", RESUME)
    detail = world.recruiter.candidate(cid)
    exp = detail["experiences"][0]
    world.reviewer.ok("patch", f"/api/claims/experiences/{exp['id']}", json={"title": "Charge Nurse, Medical ICU", "note": "Per reference check"})
    skill = detail["skills"][0]
    world.reviewer.ok("post", f"/api/claims/skills/{skill['id']}/review", json={"action": "reject", "note": "Not supported"})

    world.recruiter.ok("post", f"/api/documents/{doc['id']}/process", status=202)
    assert run_now(doc["job"]["id"]) == "succeeded"

    after = world.recruiter.candidate(cid)
    titles = [e["title"] for e in after["experiences"]]
    assert "Charge Nurse, Medical ICU" in titles  # correction kept
    rejected = [s for s in after["skills"] if s["id"] == skill["id"]]
    assert rejected and rejected[0]["review_state"] == "rejected"  # decision kept
    assert len(after["credentials"]) == 1  # unreviewed machine claims replaced, not duplicated


def test_stale_lease_is_reclaimed(world):
    cid = new_candidate(world)
    job_id = world.recruiter.upload(cid, "r.txt", RESUME, process=False)["job"]["id"]
    with SessionLocal() as db:
        claim(db, job_id)
        db.get(ProcessingJob, job_id).locked_at = utcnow() - timedelta(hours=1)
        db.commit()
        assert reclaim_stale(db) == 1
    job = job_row(job_id)
    assert job.status == "pending" and job.error_code == "processing_timeout"
