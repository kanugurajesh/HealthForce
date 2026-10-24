"""Turns untrusted provider output into grounded, reviewable claims.

Guarantees (each covered by tests):
- Malformed top-level output fails the job (retryable); malformed *items* are dropped with a warning.
- Unknown keys are ignored and reported; they can never reach the database.
- A claim survives only if its evidence quote or its key name is literally present in the document.
- Dates, identifiers, issuers, employers and institutions are kept only if their literal text is
  present in the document; dates are parsed here, never by the provider.
- Every machine concern becomes a human-readable flag on the claim, which forces review.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.dates import is_present, parse_date_text
from app.domain import (
    CREDENTIAL_CATALOG,
    QUALIFICATION_CATALOG,
    SKILL_CATALOG,
    EvidenceStatus,
    classify_settings,
    match_catalog,
)
from app.extraction.errors import ExtractionError
from app.extraction.schemas import (
    ITEM_MODELS,
    ExtractedCredential,
    ExtractedExperience,
    ExtractedQualification,
    ExtractedSkill,
)
from app.extraction.text import EvidenceLocator

INJECTION_FLAG = "Source document contains instruction-like text (possible prompt injection). Check this value against the document."
MAX_QUOTE = 600


@dataclass
class PlannedClaim:
    kind: str  # experience | qualification | skill | credential
    fields: dict[str, Any]
    evidence_quote: str | None
    evidence_start: int | None
    evidence_end: int | None
    evidence_status: EvidenceStatus
    flags: list[str] = field(default_factory=list)

    def dedupe_key(self) -> tuple[Any, ...]:
        f = self.fields
        if self.kind == "credential":
            ident = re.sub(r"[^A-Z0-9]", "", (f.get("identifier") or "").upper())
            return ("credential", f["type_code"], ident, f.get("expiration_date"), f.get("issue_date"))
        if self.kind == "skill":
            return ("skill", f["code"], f["name"].lower() if f["code"] == "other" else "")
        if self.kind == "qualification":
            return ("qualification", f["code"], (f.get("institution") or "").lower())
        return ("experience", f["title"].lower(), f.get("start_date"))


@dataclass
class ExtractionPlan:
    claims: list[PlannedClaim]
    warnings: list[str]
    summary: str | None
    candidate_name: str | None
    document_type: str
    stats: dict[str, Any]


class _Grounder:
    def __init__(self, text: str) -> None:
        self.loc = EvidenceLocator(text)
        self.warnings: list[str] = []
        self.dropped = 0

    def evidence(self, quote: str | None) -> tuple[str | None, int | None, int | None, EvidenceStatus]:
        span = self.loc.locate(quote)
        if span:
            return self.loc.text[span[0] : span[1]][:MAX_QUOTE], span[0], span[1], EvidenceStatus.FOUND
        return (quote or "")[:MAX_QUOTE] or None, None, None, EvidenceStatus.NOT_FOUND

    def grounded_value(self, value: str | None, what: str, flags: list[str], *, compact: bool = False) -> str | None:
        if not value:
            return None
        ok = self.loc.contains_compact(value) if compact else self.loc.contains(value)
        if ok:
            return value.strip()[:200]
        flags.append(f"{what} '{value[:60]}' was not found in the document and was discarded.")
        return None

    def drop(self, kind: str, label: str, why: str) -> None:
        self.dropped += 1
        self.warnings.append(f"Discarded {kind} '{label[:60]}': {why}")


def _date(g: _Grounder, text: str | None, what: str, flags: list[str], *, period_end: bool, flag_precision: bool = False):
    """Return (date|None, precision|None, raw_text|None) keeping only grounded, parseable dates."""
    if not text:
        return None, None, None
    if is_present(text):
        return None, None, text
    if not g.loc.contains(text):
        flags.append(f"{what} '{text[:40]}' was not found in the document and was discarded.")
        return None, None, None
    parsed = parse_date_text(text, period_end=period_end)
    if parsed is None:
        flags.append(f"{what} '{text[:40]}' is in an unrecognized format; enter it manually.")
        return None, None, text
    if flag_precision and parsed.precision != "day":
        flags.append(f"{what} '{text}' has {parsed.precision} precision; interpreted as {parsed.value:%b %d, %Y}.")
    return parsed.value, parsed.precision, text


def _credential(g: _Grounder, item: ExtractedCredential) -> PlannedClaim | None:
    flags: list[str] = []
    quote, start, end, status = g.evidence(item.evidence_quote)
    if status == EvidenceStatus.NOT_FOUND and not g.loc.contains(item.name):
        g.drop("credential", item.name, "no supporting text in the document")
        return None
    entry = match_catalog(CREDENTIAL_CATALOG, item.name) or match_catalog(CREDENTIAL_CATALOG, quote or "")
    if entry is None:
        flags.append("Credential type not recognized; classify it manually.")
    if status == EvidenceStatus.NOT_FOUND:
        flags.append("Evidence quote could not be located in the document.")
    # Only expiration precision affects status, so only it is flagged for a human to confirm.
    exp, _, exp_text = _date(g, item.expiration_date_text, "Expiration date", flags, period_end=True, flag_precision=True)
    issued, _, _ = _date(g, item.issue_date_text, "Issue date", flags, period_end=False)
    if exp and issued and issued > exp:
        flags.append("Issue date is after the expiration date; both dates were discarded for manual entry.")
        exp = issued = None
    return PlannedClaim(
        "credential",
        {
            "type_code": entry.code if entry else "OTHER",
            "name": item.name[:200],
            "issuer": g.grounded_value(item.issuer, "Issuer", flags),
            "identifier": g.grounded_value(item.identifier, "Identifier", flags, compact=True),
            "jurisdiction": g.grounded_value(item.jurisdiction, "Jurisdiction", flags),
            "issue_date": issued,
            "expiration_date": exp,
            "expiration_text": exp_text,
        },
        quote,
        start,
        end,
        status,
        flags,
    )


def _experience(g: _Grounder, item: ExtractedExperience) -> PlannedClaim | None:
    flags: list[str] = []
    quote, start, end, status = g.evidence(item.evidence_quote)
    if status == EvidenceStatus.NOT_FOUND and not g.loc.contains(item.title):
        g.drop("experience", item.title, "no supporting text in the document")
        return None
    if status == EvidenceStatus.NOT_FOUND:
        flags.append("Evidence quote could not be located in the document.")
    start_d, _, start_text = _date(g, item.start_date_text, "Start date", flags, period_end=False)
    current = is_present(item.end_date_text)
    end_d, _, end_text = (None, None, item.end_date_text) if current else _date(g, item.end_date_text, "End date", flags, period_end=True)
    if start_d and end_d and end_d < start_d:
        flags.append("End date precedes start date; dates discarded for manual entry.")
        start_d = end_d = None
    if start_d is None:
        flags.append("No usable start date; experience duration cannot be computed.")
    employer = g.grounded_value(item.employer, "Employer", flags)
    description = (item.description or "")[:1000] or None
    settings = classify_settings(item.title, employer, description)
    if not settings:
        flags.append("Care setting could not be classified; set it manually if relevant.")
    return PlannedClaim(
        "experience",
        {
            "title": item.title[:200],
            "employer": employer,
            "start_date": start_d,
            "end_date": end_d,
            "is_current": current,
            "start_text": start_text,
            "end_text": end_text,
            "description": description,
            "settings": settings,
        },
        quote,
        start,
        end,
        status,
        flags,
    )


def _qualification(g: _Grounder, item: ExtractedQualification) -> PlannedClaim | None:
    flags: list[str] = []
    quote, start, end, status = g.evidence(item.evidence_quote)
    if status == EvidenceStatus.NOT_FOUND and not g.loc.contains(item.name):
        g.drop("qualification", item.name, "no supporting text in the document")
        return None
    if status == EvidenceStatus.NOT_FOUND:
        flags.append("Evidence quote could not be located in the document.")
    entry = match_catalog(QUALIFICATION_CATALOG, item.name) or match_catalog(QUALIFICATION_CATALOG, quote or "")
    if entry is None:
        flags.append("Qualification not recognized; classify it manually.")
    if re.search(r"\b(expected|anticipated|in progress|candidate for|pursuing)\b", quote or "", re.I):
        flags.append("The document suggests this qualification may not be completed yet (e.g. 'expected'). Confirm before accepting.")
    year = None
    if item.completion_year_text and (m := re.search(r"\b(19|20)\d{2}\b", item.completion_year_text)):
        if g.loc.contains(m.group(0)):
            year = int(m.group(0))
        else:
            flags.append("Completion year was not found in the document and was discarded.")
    return PlannedClaim(
        "qualification",
        {
            "code": entry.code if entry else "OTHER",
            "name": item.name[:200],
            "institution": g.grounded_value(item.institution, "Institution", flags),
            "completion_year": year,
        },
        quote,
        start,
        end,
        status,
        flags,
    )


def _skill(g: _Grounder, item: ExtractedSkill) -> PlannedClaim | None:
    flags: list[str] = []
    quote, start, end, status = g.evidence(item.evidence_quote)
    if status == EvidenceStatus.NOT_FOUND and not g.loc.contains(item.name):
        g.drop("skill", item.name, "no supporting text in the document")
        return None
    if status == EvidenceStatus.NOT_FOUND:
        flags.append("Evidence quote could not be located in the document.")
    entry = match_catalog(SKILL_CATALOG, item.name)
    return PlannedClaim("skill", {"code": entry.code if entry else "other", "name": item.name[:200]}, quote, start, end, status, flags)


_BUILDERS: dict[str, tuple[type[BaseModel], Callable[[_Grounder, Any], PlannedClaim | None]]] = {
    "credentials": (ExtractedCredential, _credential),
    "experiences": (ExtractedExperience, _experience),
    "qualifications": (ExtractedQualification, _qualification),
    "skills": (ExtractedSkill, _skill),
}


def build_plan(raw: Any, text: str, *, injection_signals: list[str] | None = None) -> ExtractionPlan:
    """Validate and ground provider output against the (redacted) document text."""
    if not isinstance(raw, dict):
        raise ExtractionError("provider_invalid_output", "The extraction provider returned malformed output.", retryable=True)

    g = _Grounder(text)
    claims: list[PlannedClaim] = []
    for key, (model, builder) in _BUILDERS.items():
        items = raw.get(key)
        if items is None:
            g.warnings.append(f"Provider output omitted '{key}'; treated as none found.")
            continue
        if not isinstance(items, list):
            raise ExtractionError("provider_invalid_output", f"The extraction provider returned malformed '{key}'.", retryable=True)
        allowed = set(ITEM_MODELS[key].model_fields)
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                g.drop(key[:-1], f"#{idx + 1}", "item is not an object")
                continue
            unexpected = sorted(set(item) - allowed)
            if unexpected:
                g.warnings.append(f"Ignored unexpected field(s) {', '.join(unexpected)} in {key}[{idx}].")
            try:
                parsed = model.model_validate(item)
            except ValidationError as exc:
                problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors())
                g.drop(key[:-1], f"#{idx + 1}", f"invalid fields ({problems})")
                continue
            claim = builder(g, parsed)
            if claim:
                claims.append(claim)

    unique: dict[tuple[Any, ...], PlannedClaim] = {}
    for c in claims:
        unique.setdefault(c.dedupe_key(), c)
    claims = list(unique.values())

    if injection_signals:
        for c in claims:
            c.flags.insert(0, INJECTION_FLAG)
        g.warnings.append("Instruction-like text detected in the document: " + ", ".join(injection_signals) + ".")

    summary = raw.get("summary") if isinstance(raw.get("summary"), str) else None
    name = raw.get("candidate_name") if isinstance(raw.get("candidate_name"), str) else None
    doc_type = str(raw["document_type"]) if raw.get("document_type") in ("resume", "credential", "other") else "other"
    notes = [n for n in raw.get("extraction_notes") or [] if isinstance(n, str)][:10]
    g.warnings.extend(f"Provider note: {n[:200]}" for n in notes)

    counts = {k: sum(1 for c in claims if c.kind == k) for k in ("experience", "qualification", "skill", "credential")}
    return ExtractionPlan(
        claims=claims,
        warnings=g.warnings,
        summary=summary.strip()[:800] if summary else None,
        candidate_name=name.strip()[:200] if name else None,
        document_type=doc_type,
        stats={"claims": counts, "dropped": g.dropped, "flagged": sum(1 for c in claims if c.flags)},
    )
