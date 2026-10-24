"""Deterministic, explainable candidate ↔ job matching.

Every requirement evaluates to one outcome:
  met      — reviewed evidence satisfies it
  pending  — evidence exists but awaits human review or verification
  unknown  — no evidence either way (missing information is NOT treated as failure)
  not_met  — evidence establishes it is not satisfied (expired/rejected credential, too little documented experience)

Eligibility depends only on *required* requirements. The score is a transparent weighted
average and never overrides eligibility. Nothing here rejects a candidate; it supports a
human decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.domain import (
    ACUTE_CARE_SETTINGS,
    CredentialStatus,
    Eligibility,
    RequirementKind,
    RequirementOutcome,
    ReviewState,
    qualification_label,
    skill_label,
)
from app.rules.credentials import (
    PENDING_STATUSES,
    SATISFYING_STATUSES,
    CredentialAssessment,
    CredentialFacts,
    best_for_codes,
)

CREDIT = {
    RequirementOutcome.MET: 1.0,
    RequirementOutcome.PENDING: 0.5,
    RequirementOutcome.UNKNOWN: 0.0,
    RequirementOutcome.NOT_MET: 0.0,
}
ELIGIBILITY_RANK = {
    Eligibility.MEETS_ALL_REQUIRED: 0,
    Eligibility.PENDING: 1,
    Eligibility.MISSING_INFORMATION: 2,
    Eligibility.REQUIREMENT_NOT_MET: 3,
}
DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class RequirementSpec:
    id: str
    kind: RequirementKind
    label: str
    codes: tuple[str, ...] = ()
    is_required: bool = True
    weight: int = 3
    min_years: float | None = None
    setting: str | None = None  # experience: "any" | "acute_care" | ExperienceSetting value
    min_valid_days: int | None = None


@dataclass(frozen=True)
class ClaimFacts:
    """A qualification or skill claim."""

    id: str
    code: str
    review_state: ReviewState
    evidence_quote: str | None = None
    document_id: str | None = None


@dataclass(frozen=True)
class ExperienceFacts:
    id: str
    title: str
    start_date: date | None
    end_date: date | None
    is_current: bool
    settings: tuple[str, ...]
    review_state: ReviewState
    evidence_quote: str | None = None
    document_id: str | None = None


@dataclass(frozen=True)
class CandidateFacts:
    credentials: Sequence[CredentialFacts]
    credential_assessments: dict[str, CredentialAssessment]
    qualifications: Sequence[ClaimFacts]
    skills: Sequence[ClaimFacts]
    experiences: Sequence[ExperienceFacts]


@dataclass
class EvidenceRef:
    claim_type: str
    claim_id: str
    document_id: str | None
    quote: str | None
    review_state: str
    status: str | None = None


@dataclass
class RequirementResult:
    requirement_id: str
    kind: RequirementKind
    label: str
    is_required: bool
    weight: int
    outcome: RequirementOutcome
    explanation: str
    points_earned: float
    points_possible: float
    evidence: list[EvidenceRef] = field(default_factory=list)
    next_action: str | None = None


@dataclass
class NextAction:
    priority: int  # lower = more urgent
    label: str
    requirement_id: str | None = None


@dataclass
class MatchResult:
    score: int  # 0-100
    eligibility: Eligibility
    eligibility_explanation: str
    requirements: list[RequirementResult]
    satisfied: int
    not_satisfied: int
    pending: int
    unknown: int
    next_actions: list[NextAction]
    score_explanation: str


# --------------------------------------------------------------------------- credentials


def _eval_credential(req: RequirementSpec, facts: CandidateFacts, as_of: date) -> tuple[RequirementOutcome, str, list[EvidenceRef], str | None, int]:
    records = {c.id: c for c in facts.credentials}
    result = best_for_codes(req.codes, facts.credential_assessments.values(), records)
    evidence = [
        EvidenceRef(
            "credential",
            a.credential_id,
            records[a.credential_id].document_id,
            records[a.credential_id].evidence_quote,
            records[a.credential_id].review_state.value,
            a.status.value,
        )
        for a in result.candidates
    ]
    label = result.label
    best = result.best
    if best is None:
        return (RequirementOutcome.UNKNOWN, f"No {label} on file.", evidence, f"Request a copy of the candidate's {label}.", 30)

    rec = records[best.credential_id]
    reason = best.reasons[0] if best.reasons else ""
    status = best.status
    min_days = req.min_valid_days or 0
    exp = rec.expiration_date
    too_short = bool(min_days and exp and exp < as_of + timedelta(days=min_days))

    if status in SATISFYING_STATUSES:
        if too_short:
            return (
                RequirementOutcome.NOT_MET,
                f"{label} is valid but expires {exp:%b %d, %Y}; this role requires at least {min_days} days of remaining validity.",
                evidence,
                f"Request proof of {label} renewal.",
                15,
            )
        if status == CredentialStatus.EXPIRING_SOON:
            return (RequirementOutcome.MET, f"{label}: {reason}", evidence, f"Request renewal of {label} (expires {exp:%b %d, %Y}).", 75)
        return (RequirementOutcome.MET, f"{label}: {reason}", evidence, None, 99)
    if status in PENDING_STATUSES:
        extra = f" Note: expires {exp:%b %d, %Y}, inside the required {min_days}-day validity window." if too_short else ""
        action, prio = (f"Review the extracted {label}.", 40) if status == CredentialStatus.PENDING_REVIEW else (f"Verify {label} with the primary source.", 45)
        return (RequirementOutcome.PENDING, f"{label}: {reason}{extra}", evidence, action, prio)
    if status == CredentialStatus.UNABLE_TO_DETERMINE:
        return (RequirementOutcome.UNKNOWN, f"{label}: {reason}", evidence, f"Resolve {label}: {reason}", 20)
    if status == CredentialStatus.EXPIRED:
        return (RequirementOutcome.NOT_MET, f"{label}: {reason}", evidence, f"Request renewed {label}.", 10)
    # rejected
    return (RequirementOutcome.NOT_MET, f"{label}: {reason}", evidence, f"Request a valid {label}.", 10)


# --------------------------------------------------------------------------- qualifications & skills


def _eval_claims(req: RequirementSpec, claims: Sequence[ClaimFacts], noun: str, label_fn) -> tuple[RequirementOutcome, str, list[EvidenceRef], str | None, int]:  # type: ignore[no-untyped-def]
    relevant = [c for c in claims if c.code in req.codes and c.review_state != ReviewState.REJECTED]
    evidence = [EvidenceRef(noun, c.id, c.document_id, c.evidence_quote, c.review_state.value) for c in relevant]
    names = " or ".join(label_fn(code) for code in req.codes)
    reviewed = [c for c in relevant if c.review_state in (ReviewState.ACCEPTED, ReviewState.CORRECTED)]
    if reviewed:
        return (RequirementOutcome.MET, f"{names}: confirmed by reviewed evidence.", evidence, None, 99)
    if relevant:
        return (RequirementOutcome.PENDING, f"{names}: found in documents, awaiting review.", evidence, f"Review the extracted {names}.", 50)
    return (
        RequirementOutcome.UNKNOWN,
        f"No evidence of {names} in the candidate's documents. Absence of evidence is not treated as a failure.",
        evidence,
        f"Ask the candidate to confirm {names}.",
        60 if req.is_required else 80,
    )


# --------------------------------------------------------------------------- experience


def _setting_matches(setting: str | None, entry_settings: Sequence[str]) -> bool:
    if not setting or setting == "any":
        return True
    if setting == "acute_care":
        return any(s in {x.value for x in ACUTE_CARE_SETTINGS} for s in entry_settings)
    return setting in entry_settings


def merged_years(intervals: Sequence[tuple[date, date]]) -> float:
    """Total years covered by possibly-overlapping intervals (overlaps counted once)."""
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total_days = 0
    cur_start, cur_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total_days += (cur_end - cur_start).days
            cur_start, cur_end = start, end
    total_days += (cur_end - cur_start).days
    return total_days / DAYS_PER_YEAR


def _setting_text(setting: str | None) -> str:
    if not setting or setting == "any":
        return ""
    return " " + setting.replace("_", " ")


def _eval_experience(req: RequirementSpec, exps: Sequence[ExperienceFacts], as_of: date) -> tuple[RequirementOutcome, str, list[EvidenceRef], str | None, int]:
    min_years = req.min_years or 0.0
    setting_txt = _setting_text(req.setting)
    live = [e for e in exps if e.review_state != ReviewState.REJECTED]
    matching = [e for e in live if _setting_matches(req.setting, e.settings)]
    unclassified = [e for e in live if not e.settings and req.setting not in (None, "any")]
    evidence = [EvidenceRef("experience", e.id, e.document_id, e.evidence_quote, e.review_state.value) for e in matching]

    def interval(e: ExperienceFacts) -> tuple[date, date] | None:
        end = as_of if e.is_current else e.end_date
        if e.start_date is None or end is None or end < e.start_date:
            return None
        return (e.start_date, min(end, as_of))

    dated_all = [iv for e in matching if (iv := interval(e))]
    dated_reviewed = [iv for e in matching if e.review_state in (ReviewState.ACCEPTED, ReviewState.CORRECTED) and (iv := interval(e))]
    undated = [e for e in matching if interval(e) is None]
    years_all = merged_years(dated_all)
    years_reviewed = merged_years(dated_reviewed)
    need = f"{min_years:g}+ years{setting_txt} experience"

    if years_reviewed >= min_years and matching:
        return (RequirementOutcome.MET, f"{years_reviewed:.1f} years of reviewed{setting_txt} experience (requires {need}).", evidence, None, 99)
    if years_all >= min_years and matching:
        return (
            RequirementOutcome.PENDING,
            f"{years_all:.1f} years of{setting_txt} experience documented (requires {need}); awaiting review.",
            evidence,
            "Review the candidate's work history.",
            50,
        )
    if not live:
        return (RequirementOutcome.UNKNOWN, "No work history has been extracted.", evidence, "Request a resume with work history.", 35)
    if undated or unclassified:
        why = []
        if undated:
            why.append(f"{len(undated)} relevant role(s) lack usable dates")
        if unclassified:
            why.append(f"{len(unclassified)} role(s) could not be classified by care setting")
        return (
            RequirementOutcome.UNKNOWN,
            f"{years_all:.1f} years documented so far (requires {need}), but " + " and ".join(why) + ".",
            evidence,
            f"Confirm the candidate's{setting_txt} experience dates.",
            35,
        )
    return (
        RequirementOutcome.NOT_MET,
        f"Documented{setting_txt} experience totals {years_all:.1f} years; the role requires {need}.",
        evidence,
        None,
        70,
    )


# --------------------------------------------------------------------------- aggregate


def evaluate_match(reqs: Sequence[RequirementSpec], facts: CandidateFacts, as_of: date) -> MatchResult:
    results: list[RequirementResult] = []
    actions: list[NextAction] = []
    for req in reqs:
        if req.kind == RequirementKind.CREDENTIAL:
            outcome, expl, ev, action, prio = _eval_credential(req, facts, as_of)
        elif req.kind == RequirementKind.QUALIFICATION:
            outcome, expl, ev, action, prio = _eval_claims(req, facts.qualifications, "qualification", qualification_label)
        elif req.kind == RequirementKind.SKILL:
            outcome, expl, ev, action, prio = _eval_claims(req, facts.skills, "skill", skill_label)
        else:
            outcome, expl, ev, action, prio = _eval_experience(req, facts.experiences, as_of)
        possible = float(req.weight)
        results.append(
            RequirementResult(
                requirement_id=req.id,
                kind=req.kind,
                label=req.label,
                is_required=req.is_required,
                weight=req.weight,
                outcome=outcome,
                explanation=expl,
                points_earned=round(possible * CREDIT[outcome], 2),
                points_possible=possible,
                evidence=ev,
                next_action=action,
            )
        )
        if action:
            # Preferred requirements are never more urgent than required ones.
            actions.append(NextAction(prio if req.is_required else prio + 100, action, req.id))

    required = [r for r in results if r.is_required]
    outcomes = {r.outcome for r in required}
    if RequirementOutcome.NOT_MET in outcomes:
        failing = [r.label for r in required if r.outcome == RequirementOutcome.NOT_MET]
        eligibility, elig_expl = Eligibility.REQUIREMENT_NOT_MET, "Required requirement not met: " + "; ".join(failing) + "."
    elif RequirementOutcome.UNKNOWN in outcomes:
        missing = [r.label for r in required if r.outcome == RequirementOutcome.UNKNOWN]
        eligibility, elig_expl = Eligibility.MISSING_INFORMATION, "Missing information for: " + "; ".join(missing) + "."
    elif RequirementOutcome.PENDING in outcomes:
        pend = [r.label for r in required if r.outcome == RequirementOutcome.PENDING]
        eligibility, elig_expl = Eligibility.PENDING, "Awaiting review or verification: " + "; ".join(pend) + "."
    else:
        eligibility, elig_expl = Eligibility.MEETS_ALL_REQUIRED, "Every required requirement is met by reviewed evidence."

    earned = sum(r.points_earned for r in results)
    possible = sum(r.points_possible for r in results)
    score = round(100 * earned / possible) if possible else 0
    actions.sort(key=lambda a: a.priority)
    count = lambda o: sum(1 for r in results if r.outcome == o)  # noqa: E731
    return MatchResult(
        score=score,
        eligibility=eligibility,
        eligibility_explanation=elig_expl,
        requirements=results,
        satisfied=count(RequirementOutcome.MET),
        not_satisfied=count(RequirementOutcome.NOT_MET),
        pending=count(RequirementOutcome.PENDING),
        unknown=count(RequirementOutcome.UNKNOWN),
        next_actions=actions,
        score_explanation=(
            f"Score = weighted points earned / possible = {earned:g} / {possible:g}. "
            "Each requirement is worth its weight; met earns full weight, pending earns half, "
            "unknown and not met earn zero. The score ranks candidates within an eligibility tier "
            "and never overrides an unmet required requirement."
        ),
    )
