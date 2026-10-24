"""Provider-facing extraction schema.

This is the ONLY shape an extraction provider may return. Deliberately absent: any status,
verification, validity, score or recommendation field — a document (or a prompt injection
inside it) cannot set those, because the schema has nowhere to put them.

Dates are returned as the raw text printed in the document; app.dates parses them.
"""

from __future__ import annotations

import types
from functools import cache
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict


class _Item(BaseModel):
    # Unknown keys are ignored (and reported as warnings by the pipeline), never stored.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    evidence_quote: str


class ExtractedExperience(_Item):
    title: str
    employer: str | None = None
    start_date_text: str | None = None
    end_date_text: str | None = None
    description: str | None = None


class ExtractedQualification(_Item):
    name: str
    institution: str | None = None
    completion_year_text: str | None = None


class ExtractedSkill(_Item):
    name: str


class ExtractedCredential(_Item):
    name: str
    issuer: str | None = None
    identifier: str | None = None
    jurisdiction: str | None = None
    issue_date_text: str | None = None
    expiration_date_text: str | None = None


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    candidate_name: str | None = None
    document_type: Literal["resume", "credential", "other"] = "other"
    summary: str | None = None
    experiences: list[ExtractedExperience] = []
    qualifications: list[ExtractedQualification] = []
    skills: list[ExtractedSkill] = []
    credentials: list[ExtractedCredential] = []
    extraction_notes: list[str] = []


ITEM_MODELS: dict[str, type[_Item]] = {
    "experiences": ExtractedExperience,
    "qualifications": ExtractedQualification,
    "skills": ExtractedSkill,
    "credentials": ExtractedCredential,
}


# --------------------------------------------------------------------------- strict JSON schema

_PRIMITIVES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _schema_for(annotation: Any) -> dict[str, Any]:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        inner = [a for a in args if a is not type(None)]
        if len(inner) != 1 or len(inner) == len(args):
            raise TypeError(f"Unsupported union {annotation!r}")
        schema = _schema_for(inner[0])
        if isinstance(schema.get("type"), str):
            return {**schema, "type": [schema["type"], "null"]}
        return {"anyOf": [schema, {"type": "null"}]}
    if origin is list:
        return {"type": "array", "items": _schema_for(args[0])}
    if origin is Literal:
        return {"type": "string", "enum": list(args)}
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        props = {name: _schema_for(field.annotation) for name, field in annotation.model_fields.items()}
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    if annotation in _PRIMITIVES:
        return {"type": _PRIMITIVES[annotation]}
    raise TypeError(f"Unsupported annotation {annotation!r}")


@cache
def strict_json_schema() -> dict[str, Any]:
    """ExtractionOutput as a strict-mode JSON schema: every property required, optional values
    expressed as nullable types, and additionalProperties=false on every object."""
    return _schema_for(ExtractionOutput)
