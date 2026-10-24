"""API request/response contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain import (
    CREDENTIAL_CATALOG,
    EXPERIENCE_REQUIREMENT_SETTINGS,
    QUALIFICATION_CATALOG,
    SKILL_CATALOG,
    CandidateStatus,
    Decision,
    DocumentKind,
    ExperienceSetting,
    JobRoleStatus,
    NoteKind,
    RequirementKind,
    Role,
    TaskKind,
    TaskStatus,
    VerificationMethod,
)

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")


def _check_email(v: str | None) -> str | None:
    if v and not _EMAIL.match(v):
        raise ValueError("Enter a valid email address.")
    return v.lower() if v else None


def _check_credential_type(v: str | None) -> str | None:
    if v is not None and v not in CREDENTIAL_CATALOG and v != "OTHER":
        raise ValueError("Unknown credential type.")
    return v


Email = Annotated[str | None, Field(default=None, max_length=254), AfterValidator(_check_email)]
CredentialType = Annotated[str, AfterValidator(_check_credential_type)]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# =========================================================================== inputs


class LoginIn(In):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=200)


class CandidateCreate(In):
    full_name: str = Field(min_length=1, max_length=200)
    email: Email = None
    location: str | None = Field(default=None, max_length=120)
    headline: str | None = Field(default=None, max_length=200)
    job_id: str | None = None


class CandidateUpdate(In):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: Email = None
    location: str | None = Field(default=None, max_length=120)
    headline: str | None = Field(default=None, max_length=200)
    job_id: str | None = None


class SummaryUpdate(In):
    summary: str = Field(min_length=1, max_length=2000)


class StatusChange(In):
    status: CandidateStatus
    reason: str | None = Field(default=None, max_length=1000)


class NoteCreate(In):
    kind: NoteKind = NoteKind.NOTE
    decision: Decision | None = None
    body: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def _decision(self) -> NoteCreate:
        if self.kind == NoteKind.DECISION and self.decision is None:
            raise ValueError("A decision note must include a decision.")
        if self.kind == NoteKind.NOTE and self.decision is not None:
            raise ValueError("Plain notes cannot carry a decision.")
        return self


class ClaimReview(In):
    action: Literal["accept", "reject"]
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _note(self) -> ClaimReview:
        if self.action == "reject" and not self.note:
            raise ValueError("A reason is required when rejecting extracted data.")
        return self


class CredentialPatch(In):
    type_code: CredentialType | None = None
    issuer: str | None = Field(default=None, max_length=200)
    identifier: str | None = Field(default=None, max_length=80)
    jurisdiction: str | None = Field(default=None, max_length=80)
    issue_date: date | None = None
    expiration_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class ExperiencePatch(In):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    employer: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    settings: list[ExperienceSetting] | None = None
    note: str | None = Field(default=None, max_length=1000)


class QualificationPatch(In):
    code: str | None = None
    institution: str | None = Field(default=None, max_length=200)
    completion_year: int | None = Field(default=None, ge=1950, le=2100)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is not None and v not in QUALIFICATION_CATALOG and v != "OTHER":
            raise ValueError("Unknown qualification.")
        return v


class SkillPatch(In):
    code: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is not None and v not in SKILL_CATALOG and v != "other":
            raise ValueError("Unknown skill.")
        return v


class ManualCredentialCreate(In):
    type_code: CredentialType
    issuer: str | None = Field(default=None, max_length=200)
    identifier: str | None = Field(default=None, max_length=80)
    jurisdiction: str | None = Field(default=None, max_length=80)
    issue_date: date | None = None
    expiration_date: date | None = None
    note: str = Field(min_length=3, max_length=1000, description="Where this information came from.")

    @model_validator(mode="after")
    def _dates(self) -> ManualCredentialCreate:
        if self.issue_date and self.expiration_date and self.issue_date > self.expiration_date:
            raise ValueError("Issue date must be on or before the expiration date.")
        return self


class VerificationIn(In):
    outcome: Literal["verified", "failed"]
    method: VerificationMethod
    reference: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _reference(self) -> VerificationIn:
        if self.method == VerificationMethod.MANUAL_PRIMARY_SOURCE and not self.reference:
            raise ValueError("Record which primary source was checked (e.g. board lookup and date).")
        if self.method == VerificationMethod.SIMULATED and self.outcome != "verified":
            raise ValueError("Simulated verification can only produce a simulated 'verified' result.")
        return self


class RequirementIn(In):
    kind: RequirementKind
    codes: list[str] = Field(default_factory=list, max_length=6)
    label: str | None = Field(default=None, max_length=200)
    is_required: bool = True
    weight: int = Field(default=3, ge=1, le=5)
    min_years: float | None = Field(default=None, ge=0, le=40)
    setting: str | None = None
    min_valid_days: int | None = Field(default=None, ge=0, le=730)

    @model_validator(mode="after")
    def _consistent(self) -> RequirementIn:
        catalog = {
            RequirementKind.CREDENTIAL: CREDENTIAL_CATALOG,
            RequirementKind.QUALIFICATION: QUALIFICATION_CATALOG,
            RequirementKind.SKILL: SKILL_CATALOG,
        }.get(self.kind)
        if catalog is not None:
            if not self.codes:
                raise ValueError("Select at least one item for this requirement.")
            unknown = [c for c in self.codes if c not in catalog]
            if unknown:
                raise ValueError(f"Unknown {self.kind.value} code(s): {', '.join(unknown)}.")
            if self.min_years is not None or self.setting is not None:
                raise ValueError("Years and setting apply only to experience requirements.")
        else:
            if self.codes:
                raise ValueError("Experience requirements do not take codes.")
            if self.min_years is None:
                raise ValueError("Experience requirements need a minimum number of years.")
            self.setting = self.setting or "any"
            if self.setting not in EXPERIENCE_REQUIREMENT_SETTINGS:
                raise ValueError(f"Setting must be one of: {', '.join(EXPERIENCE_REQUIREMENT_SETTINGS)}.")
        if self.min_valid_days is not None and self.kind != RequirementKind.CREDENTIAL:
            raise ValueError("Minimum remaining validity applies only to credential requirements.")
        return self


class JobRoleIn(In):
    title: str = Field(min_length=2, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    status: JobRoleStatus = JobRoleStatus.OPEN
    requirements: list[RequirementIn] = Field(default_factory=list, max_length=30)


class TaskPatch(In):
    status: TaskStatus | None = None
    owner_id: str | None = None
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    waived_reason: str | None = Field(default=None, max_length=1000)


class TemplateTaskIn(In):
    id: str | None = None
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    kind: TaskKind = TaskKind.MANUAL
    owner_role: Role = Role.RECRUITER
    due_offset_days: int = Field(default=7, ge=0, le=180)


class TemplateIn(In):
    tasks: list[TemplateTaskIn] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _final_review(self) -> TemplateIn:
        if sum(1 for t in self.tasks if t.kind == TaskKind.FINAL_REVIEW) != 1:
            raise ValueError("The checklist must contain exactly one final review task.")
        return self


class DocumentKindIn(BaseModel):
    kind: DocumentKind


# =========================================================================== outputs


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrgOut(Out):
    id: str
    name: str


class UserOut(Out):
    id: str
    email: str
    full_name: str
    role: str
    organization: OrgOut
    permissions: list[str]


class UserBrief(Out):
    id: str
    full_name: str
    role: str


class ClaimOut(Out):
    id: str
    document_id: str | None
    source: str
    evidence_quote: str | None
    evidence_start: int | None
    evidence_end: int | None
    evidence_status: str
    review_state: str
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    review_note: str | None
    flags: list[str]
    created_at: datetime
    updated_at: datetime


class ExperienceOut(ClaimOut):
    title: str
    employer: str | None
    settings: list[str]
    start_date: date | None
    end_date: date | None
    is_current: bool
    start_text: str | None
    end_text: str | None
    description: str | None
    duration_years: float | None = None


class QualificationOut(ClaimOut):
    code: str
    label: str = ""
    name: str
    institution: str | None
    completion_year: int | None


class SkillOut(ClaimOut):
    code: str
    label: str = ""
    name: str


class CredentialOut(ClaimOut):
    type_code: str
    type_label: str = ""
    name: str
    issuer: str | None
    identifier: str | None
    jurisdiction: str | None
    issue_date: date | None
    expiration_date: date | None
    expiration_text: str | None
    verification_status: str
    verification_method: str | None
    verification_reference: str | None
    verified_at: datetime | None
    verified_by_name: str | None = None
    status: str = ""
    status_reasons: list[str] = []
    expiring_soon: bool = False
    days_until_expiry: int | None = None
    simulated_verification: bool = False
    conflicts_with: list[str] = []


class EvidenceRefOut(BaseModel):
    claim_type: str
    claim_id: str
    document_id: str | None
    quote: str | None
    review_state: str
    status: str | None


class RequirementResultOut(BaseModel):
    requirement_id: str
    kind: str
    label: str
    is_required: bool
    weight: int
    outcome: str
    explanation: str
    points_earned: float
    points_possible: float
    next_action: str | None
    evidence: list[EvidenceRefOut]


class NextActionOut(BaseModel):
    priority: int
    label: str
    requirement_id: str | None = None


class JobBrief(Out):
    id: str
    title: str


class MatchOut(BaseModel):
    job: JobBrief
    score: int
    eligibility: str
    eligibility_explanation: str
    score_explanation: str
    satisfied: int
    not_satisfied: int
    pending: int
    unknown: int
    requirements: list[RequirementResultOut]
    next_actions: list[NextActionOut]


class ExpirationOut(BaseModel):
    date: date
    type_code: str
    type_label: str
    days: int


class CandidateListItem(BaseModel):
    id: str
    full_name: str
    headline: str | None
    location: str | None
    status: str
    job: JobBrief | None
    eligibility: str | None
    score: int | None
    credential_statuses: list[str]
    missing_credentials: list[str]
    unreviewed_claims: int
    flagged_claims: int
    nearest_expiration: ExpirationOut | None
    next_action: str | None
    tasks_total: int
    tasks_done: int
    updated_at: datetime


class JobOut(Out):
    id: str
    document_id: str
    status: str
    provider: str
    attempts: int
    max_attempts: int
    error_code: str | None
    last_error: str | None
    retryable: bool
    warnings: list[str]
    stats: dict[str, Any]
    next_attempt_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class DocumentOut(BaseModel):
    id: str
    candidate_id: str
    kind: str
    original_filename: str
    content_type: str
    size_bytes: int
    page_count: int | None
    injection_suspected: bool
    injection_signals: list[str]
    created_at: datetime
    uploaded_by_name: str | None
    job: JobOut | None
    claim_counts: dict[str, int]


class DocumentDetail(DocumentOut):
    candidate_name: str
    text: str | None
    experiences: list[ExperienceOut]
    qualifications: list[QualificationOut]
    skills: list[SkillOut]
    credentials: list[CredentialOut]


class UploadOut(BaseModel):
    document: DocumentOut
    created: bool


class TaskOut(BaseModel):
    id: str
    title: str
    description: str | None
    kind: str
    owner_role: str
    owner: UserBrief | None
    status: str
    due_date: date | None
    overdue: bool
    notes: str | None
    completed_by_name: str | None
    completed_at: datetime | None
    waived_reason: str | None
    blockers: list[str]
    position: int


class NoteOut(BaseModel):
    id: str
    kind: str
    decision: str | None
    body: str
    author_name: str | None
    created_at: datetime


class AuditOut(BaseModel):
    id: str
    actor_label: str
    entity_type: str
    entity_id: str
    candidate_id: str | None
    candidate_name: str | None = None
    action: str
    summary: str
    reason: str | None
    details: dict[str, Any]
    created_at: datetime


class CandidateDetail(CandidateListItem):
    email: str | None
    summary: str | None
    summary_source: str | None
    summary_reviewed: bool
    allowed_transitions: list[str]
    experiences: list[ExperienceOut]
    qualifications: list[QualificationOut]
    skills: list[SkillOut]
    credentials: list[CredentialOut]
    documents: list[DocumentOut]
    match: MatchOut | None
    next_actions: list[NextActionOut]
    tasks: list[TaskOut]
    notes: list[NoteOut]
    clearance_blockers: list[str]
    created_at: datetime


class RequirementOut(Out):
    id: str
    kind: str
    codes: list[str]
    label: str
    is_required: bool
    weight: int
    min_years: float | None
    setting: str | None
    min_valid_days: int | None
    position: int


class JobRoleOut(BaseModel):
    id: str
    title: str
    department: str | None
    location: str | None
    description: str | None
    status: str
    requirements: list[RequirementOut]
    candidate_count: int
    created_at: datetime
    updated_at: datetime


class CandidateBrief(BaseModel):
    id: str
    full_name: str
    status: str
    headline: str | None
    assigned_to_this_job: bool


class JobMatchRow(BaseModel):
    candidate: CandidateBrief
    match: MatchOut


class JobMatchesOut(BaseModel):
    job: JobRoleOut
    results: list[JobMatchRow]


class ProcessingJobRow(JobOut):
    document_filename: str
    document_kind: str
    candidate_id: str
    candidate_name: str


class TemplateTaskOut(Out):
    id: str
    title: str
    description: str | None
    kind: str
    owner_role: str
    due_offset_days: int
    position: int


class DashboardMetrics(BaseModel):
    total_candidates: int
    active_candidates: int
    awaiting_review: int
    credential_issues: int
    ready_for_next_step: int
    in_onboarding: int
    cleared: int
    failed_jobs: int
    queued_jobs: int


class UpcomingExpiration(BaseModel):
    candidate_id: str
    candidate_name: str
    credential_id: str
    type_code: str
    type_label: str
    expiration_date: date
    days_until_expiry: int
    status: str


class DashboardAction(BaseModel):
    candidate_id: str
    candidate_name: str
    label: str
    priority: int


class DashboardOut(BaseModel):
    as_of: date
    metrics: DashboardMetrics
    pipeline: list[dict[str, Any]]
    upcoming_expirations: list[UpcomingExpiration]
    next_actions: list[DashboardAction]
    recent_activity: list[AuditOut]
