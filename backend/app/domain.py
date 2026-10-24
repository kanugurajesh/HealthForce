"""Domain vocabulary: enums and the credential / qualification / skill catalogs.

Catalog matching is deterministic. Extraction providers return names as printed in the
document; this module maps them to stable codes. Anything unmapped becomes OTHER and is
routed to human review rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    RECRUITER = "recruiter"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class CandidateStatus(StrEnum):
    NEW = "new"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    ONBOARDING = "onboarding"
    CLEARED = "cleared"  # cleared to start: all onboarding tasks + required credentials satisfied
    WITHDRAWN = "withdrawn"
    NOT_SELECTED = "not_selected"


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class ClaimSource(StrEnum):
    AI = "ai"  # produced by an external LLM provider
    MOCK = "mock"  # produced by the offline heuristic extractor
    MANUAL = "manual"  # entered by a user


class EvidenceStatus(StrEnum):
    FOUND = "found"  # quote located verbatim (normalized) in the source document
    NOT_FOUND = "not_found"  # provider quote could not be located: treat claim as unsupported
    NONE = "none"  # manual entry, no document evidence


class VerificationStatus(StrEnum):
    NOT_STARTED = "not_started"
    VERIFIED = "verified"
    FAILED = "failed"


class VerificationMethod(StrEnum):
    MANUAL_PRIMARY_SOURCE = "manual_primary_source"  # reviewer attests they checked a primary source
    SIMULATED = "simulated"  # demo only; never a real verification


class CredentialStatus(StrEnum):
    MISSING = "missing"
    PENDING_REVIEW = "pending_review"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    REJECTED = "rejected"
    UNABLE_TO_DETERMINE = "unable_to_determine"


class DocumentKind(StrEnum):
    RESUME = "resume"
    CREDENTIAL = "credential"
    OTHER = "other"


class JobState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RequirementKind(StrEnum):
    CREDENTIAL = "credential"
    QUALIFICATION = "qualification"
    SKILL = "skill"
    EXPERIENCE = "experience"


class RequirementOutcome(StrEnum):
    MET = "met"
    PENDING = "pending"  # evidence exists but awaits human review or verification
    UNKNOWN = "unknown"  # no evidence either way
    NOT_MET = "not_met"  # evidence establishes the requirement is not satisfied


class Eligibility(StrEnum):
    MEETS_ALL_REQUIRED = "meets_all_required"
    PENDING = "pending"
    MISSING_INFORMATION = "missing_information"
    REQUIREMENT_NOT_MET = "requirement_not_met"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    WAIVED = "waived"


class TaskKind(StrEnum):
    MANUAL = "manual"
    INTERVIEW = "interview"
    CREDENTIAL_CHECK = "credential_check"  # blocked until required credentials are satisfied
    FINAL_REVIEW = "final_review"  # blocked until every other task is done/waived; reviewer only


class JobRoleStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class NoteKind(StrEnum):
    NOTE = "note"
    DECISION = "decision"


class Decision(StrEnum):
    ADVANCE = "advance"
    HOLD = "hold"
    DECLINE = "decline"


class ExperienceSetting(StrEnum):
    CRITICAL_CARE = "critical_care"
    EMERGENCY = "emergency"
    MED_SURG = "med_surg"
    TELEMETRY = "telemetry"
    PEDIATRICS = "pediatrics"
    LONG_TERM_CARE = "long_term_care"
    OUTPATIENT = "outpatient"


# Settings that count as "acute care" (hospital inpatient / emergency).
ACUTE_CARE_SETTINGS = {
    ExperienceSetting.CRITICAL_CARE,
    ExperienceSetting.EMERGENCY,
    ExperienceSetting.MED_SURG,
    ExperienceSetting.TELEMETRY,
    ExperienceSetting.PEDIATRICS,
}

# Requirement "setting" values accepted on experience requirements.
EXPERIENCE_REQUIREMENT_SETTINGS = ["any", "acute_care", *[s.value for s in ExperienceSetting]]


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    label: str
    aliases: tuple[str, ...]
    expires: bool = False
    verification_source: str = ""
    _patterns: tuple[re.Pattern[str], ...] = field(default=(), compare=False, repr=False)


def _entry(code: str, label: str, aliases: list[str], **kw: object) -> CatalogEntry:
    # Word-bounded; also excludes identifier-like contexts such as "#RN-48213".
    patterns = tuple(re.compile(rf"(?<![a-z0-9#]){re.escape(a)}(?![a-z0-9])(?!-\d)", re.I) for a in aliases)
    return CatalogEntry(code, label, tuple(aliases), _patterns=patterns, **kw)  # type: ignore[arg-type]


CREDENTIAL_CATALOG: dict[str, CatalogEntry] = {
    e.code: e
    for e in [
        _entry(
            "CCRN",
            "CCRN — Critical Care Registered Nurse (certification)",
            ["ccrn", "critical care registered nurse"],
            expires=True,
            verification_source="AACN certification verification (not integrated)",
        ),
        _entry(
            "RN_LICENSE",
            "Registered Nurse (RN) License",
            ["registered nurse license", "rn license", "registered nurse (rn) license", "registered nurse", "rn"],
            expires=True,
            verification_source="State board of nursing / Nursys (not integrated)",
        ),
        _entry(
            "LPN_LICENSE",
            "Licensed Practical/Vocational Nurse License",
            ["licensed practical nurse", "licensed vocational nurse", "lpn license", "lvn license", "lpn", "lvn"],
            expires=True,
            verification_source="State board of nursing (not integrated)",
        ),
        _entry(
            "CNA_CERT",
            "Certified Nursing Assistant (CNA)",
            ["certified nursing assistant", "nurse aide registry", "cna certification", "cna"],
            expires=True,
            verification_source="State nurse aide registry (not integrated)",
        ),
        _entry(
            "ACLS",
            "Advanced Cardiovascular Life Support (ACLS)",
            ["advanced cardiovascular life support", "advanced cardiac life support", "acls"],
            expires=True,
            verification_source="Issuer eCard lookup (not integrated)",
        ),
        _entry(
            "PALS",
            "Pediatric Advanced Life Support (PALS)",
            ["pediatric advanced life support", "pals"],
            expires=True,
            verification_source="Issuer eCard lookup (not integrated)",
        ),
        _entry(
            "BLS",
            "Basic Life Support (BLS)",
            ["basic life support", "bls provider", "bls"],
            expires=True,
            verification_source="Issuer eCard lookup (not integrated)",
        ),
        _entry(
            "TB_SCREEN",
            "Tuberculosis (TB) Screening",
            ["tuberculosis screening", "tb screening", "tb test", "quantiferon", "ppd"],
            expires=True,
            verification_source="Occupational health records",
        ),
    ]
}

QUALIFICATION_CATALOG: dict[str, CatalogEntry] = {
    e.code: e
    for e in [
        _entry("MSN", "Master of Science in Nursing (MSN)", ["master of science in nursing", "msn"]),
        _entry("BSN", "Bachelor of Science in Nursing (BSN)", ["bachelor of science in nursing", "bsn"]),
        _entry(
            "ADN",
            "Associate Degree in Nursing (ADN/ASN)",
            ["associate degree in nursing", "associate of science in nursing", "associate of applied science in nursing", "adn", "asn"],
        ),
        _entry("LPN_DIPLOMA", "Practical Nursing Diploma", ["practical nursing diploma", "practical nursing certificate"]),
        _entry("CNA_TRAINING", "Nurse Aide Training Program", ["nurse aide training", "cna training program", "nursing assistant program"]),
    ]
}

SKILL_CATALOG: dict[str, CatalogEntry] = {
    e.code: e
    for e in [
        _entry("ventilator_management", "Ventilator management", ["ventilator management", "mechanical ventilation", "ventilator"]),
        _entry("hemodynamic_monitoring", "Hemodynamic monitoring", ["hemodynamic monitoring", "arterial line", "a-line"]),
        _entry("telemetry", "Telemetry / cardiac monitoring", ["telemetry", "cardiac monitoring", "ekg interpretation", "ecg interpretation"]),
        _entry("iv_therapy", "IV therapy", ["iv therapy", "iv insertion", "intravenous therapy", "iv starts"]),
        _entry("medication_administration", "Medication administration", ["medication administration", "med pass"]),
        _entry("wound_care", "Wound care", ["wound care", "wound vac"]),
        _entry("epic_ehr", "EHR — Epic", ["epic ehr", "epic"]),
        _entry("cerner_ehr", "EHR — Cerner", ["cerner"]),
        _entry("sepsis_protocols", "Sepsis protocols", ["sepsis protocols", "sepsis bundle", "sepsis"]),
        _entry("patient_education", "Patient education", ["patient education", "discharge teaching"]),
        _entry("phlebotomy", "Phlebotomy", ["phlebotomy", "venipuncture"]),
        _entry("vital_signs", "Vital signs", ["vital signs", "vitals"]),
        _entry("adl_assistance", "ADL assistance", ["activities of daily living", "adl assistance", "adls"]),
        _entry("crrt", "CRRT", ["continuous renal replacement therapy", "crrt"]),
        _entry("triage", "Triage", ["triage"]),
    ]
}

_SETTING_KEYWORDS: dict[ExperienceSetting, list[str]] = {
    ExperienceSetting.CRITICAL_CARE: ["icu", "intensive care", "critical care", "cvicu", "micu", "sicu", "ccu"],
    ExperienceSetting.EMERGENCY: ["emergency", "emergency department", "er", "ed", "trauma"],
    ExperienceSetting.MED_SURG: ["med-surg", "med/surg", "medical-surgical", "medical surgical"],
    ExperienceSetting.TELEMETRY: ["telemetry", "step-down", "stepdown", "progressive care"],
    ExperienceSetting.PEDIATRICS: ["pediatric", "picu", "nicu"],
    ExperienceSetting.LONG_TERM_CARE: ["long-term care", "long term care", "skilled nursing", "nursing home", "assisted living", "rehab"],
    ExperienceSetting.OUTPATIENT: ["outpatient", "clinic", "ambulatory", "home health"],
}
_SETTING_PATTERNS = {s: [re.compile(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", re.I) for k in kws] for s, kws in _SETTING_KEYWORDS.items()}


def match_catalog(catalog: dict[str, CatalogEntry], text: str) -> CatalogEntry | None:
    """Return the entry whose longest alias matches `text` (word-boundary, case-insensitive)."""
    best: tuple[int, CatalogEntry] | None = None
    for entry in catalog.values():
        for alias, pattern in zip(entry.aliases, entry._patterns, strict=True):
            if pattern.search(text) and (best is None or len(alias) > best[0]):
                best = (len(alias), entry)
    return best[1] if best else None


def find_all_in_catalog(catalog: dict[str, CatalogEntry], text: str) -> list[tuple[CatalogEntry, int, int]]:
    """All non-overlapping catalog mentions in text as (entry, start, end), longest alias first."""
    hits: list[tuple[CatalogEntry, int, int]] = []
    candidates: list[tuple[int, int, CatalogEntry]] = []
    for entry in catalog.values():
        for pattern in entry._patterns:
            for m in pattern.finditer(text):
                candidates.append((m.start(), m.end(), entry))
    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
    taken: list[tuple[int, int]] = []
    for start, end, entry in candidates:
        if any(start < t_end and end > t_start for t_start, t_end in taken):
            continue
        taken.append((start, end))
        hits.append((entry, start, end))
    hits.sort(key=lambda h: h[1])
    return hits


def classify_settings(*texts: str | None) -> list[str]:
    joined = " ".join(t for t in texts if t)
    return sorted(s.value for s, patterns in _SETTING_PATTERNS.items() if any(p.search(joined) for p in patterns))


def credential_label(code: str) -> str:
    entry = CREDENTIAL_CATALOG.get(code)
    return entry.label if entry else code.replace("_", " ").title()


def qualification_label(code: str) -> str:
    entry = QUALIFICATION_CATALOG.get(code)
    return entry.label if entry else code


def skill_label(code: str) -> str:
    entry = SKILL_CATALOG.get(code)
    return entry.label if entry else code.replace("_", " ")
