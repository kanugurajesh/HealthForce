"""SQLAlchemy ORM models.

Conventions:
- UUID string primary keys (no enumerable ids).
- Every tenant-owned table carries `organization_id`; all queries filter on it.
- Enum-valued columns are portable strings guarded by CHECK constraints.
- Extracted claims (experience, qualification, skill, credential) share evidence + review columns.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.db import Base, utcnow
from app.domain import (
    CandidateStatus,
    ClaimSource,
    Decision,
    DocumentKind,
    EvidenceStatus,
    JobRoleStatus,
    JobState,
    NoteKind,
    RequirementKind,
    ReviewState,
    Role,
    TaskKind,
    TaskStatus,
    VerificationMethod,
    VerificationStatus,
)


def new_id() -> str:
    return str(uuid.uuid4())


def enum_check(column: str, enum: type[StrEnum], name: str) -> CheckConstraint:
    values = ", ".join(f"'{v.value}'" for v in enum)
    return CheckConstraint(f"{column} IN ({values})", name=name)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (enum_check("role", Role, "ck_users_role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    organization: Mapped[Organization] = relationship()


class JobRole(TimestampMixin, Base):
    __tablename__ = "job_roles"
    __table_args__ = (enum_check("status", JobRoleStatus, "ck_job_roles_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=JobRoleStatus.OPEN.value, nullable=False)

    requirements: Mapped[list[JobRequirement]] = relationship(back_populates="job", cascade="all, delete-orphan", order_by="JobRequirement.position")


class JobRequirement(Base):
    __tablename__ = "job_requirements"
    __table_args__ = (
        enum_check("kind", RequirementKind, "ck_job_requirements_kind"),
        CheckConstraint("weight BETWEEN 1 AND 5", name="ck_job_requirements_weight"),
        CheckConstraint("min_years IS NULL OR min_years >= 0", name="ck_job_requirements_min_years"),
        CheckConstraint("min_valid_days IS NULL OR min_valid_days >= 0", name="ck_job_requirements_min_valid_days"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("job_roles.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Any-of list of catalog codes (credential / qualification / skill). Empty for experience.
    codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    min_years: Mapped[float | None] = mapped_column(Float)
    setting: Mapped[str | None] = mapped_column(String(40))
    min_valid_days: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    job: Mapped[JobRole] = relationship(back_populates="requirements")


class Candidate(TimestampMixin, Base):
    __tablename__ = "candidates"
    __table_args__ = (
        enum_check("status", CandidateStatus, "ck_candidates_status"),
        Index("ix_candidates_org_status", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))
    location: Mapped[str | None] = mapped_column(String(120))
    headline: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=CandidateStatus.NEW.value, nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("job_roles.id", ondelete="SET NULL"), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_source: Mapped[str | None] = mapped_column(String(20))
    summary_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped[JobRole | None] = relationship()
    documents: Mapped[list[Document]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    experiences: Mapped[list[Experience]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    qualifications: Mapped[list[Qualification]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    skills: Mapped[list[Skill]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    credentials: Mapped[list[Credential]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    tasks: Mapped[list[OnboardingTask]] = relationship(back_populates="candidate", cascade="all, delete-orphan", order_by="OnboardingTask.position")
    notes: Mapped[list[CandidateNote]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        enum_check("kind", DocumentKind, "ck_documents_kind"),
        UniqueConstraint("candidate_id", "sha256", name="uq_documents_candidate_sha256"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    injection_suspected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    injection_signals: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="documents")
    job: Mapped[ProcessingJob | None] = relationship(back_populates="document", uselist=False, cascade="all, delete-orphan")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        enum_check("status", JobState, "ck_processing_jobs_status"),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="ck_processing_jobs_attempts"),
        Index("ix_processing_jobs_status_next", "status", "next_attempt_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    # One job per document: retries and reprocessing reuse the row (idempotency anchor).
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=JobState.PENDING.value, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60))
    last_error: Mapped[str | None] = mapped_column(Text)  # user-safe message, never document content
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    document: Mapped[Document] = relationship(back_populates="job")


class ClaimMixin(TimestampMixin):
    """Evidence + human review columns shared by every extracted claim."""

    @declared_attr
    def candidate_id(cls) -> Mapped[str]:  # noqa: N805
        return mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)

    @declared_attr
    def document_id(cls) -> Mapped[str | None]:  # noqa: N805
        return mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)

    @declared_attr
    def reviewed_by(cls) -> Mapped[str | None]:  # noqa: N805
        return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    evidence_start: Mapped[int | None] = mapped_column(Integer)
    evidence_end: Mapped[int | None] = mapped_column(Integer)
    evidence_status: Mapped[str] = mapped_column(String(20), default=EvidenceStatus.NONE.value, nullable=False)
    review_state: Mapped[str] = mapped_column(String(20), default=ReviewState.UNREVIEWED.value, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(Text)
    # Machine-generated reasons this claim needs attention (e.g. "date text not found in source").
    flags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


def claim_checks(table: str) -> tuple[CheckConstraint, ...]:
    return (
        enum_check("source", ClaimSource, f"ck_{table}_source"),
        enum_check("evidence_status", EvidenceStatus, f"ck_{table}_evidence_status"),
        enum_check("review_state", ReviewState, f"ck_{table}_review_state"),
    )


class Experience(ClaimMixin, Base):
    __tablename__ = "experiences"
    __table_args__ = claim_checks("experiences")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    employer: Mapped[str | None] = mapped_column(String(200))
    settings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    start_text: Mapped[str | None] = mapped_column(String(60))
    end_text: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)

    candidate: Mapped[Candidate] = relationship(back_populates="experiences")


class Qualification(ClaimMixin, Base):
    __tablename__ = "qualifications"
    __table_args__ = claim_checks("qualifications")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(200))
    completion_year: Mapped[int | None] = mapped_column(Integer)

    candidate: Mapped[Candidate] = relationship(back_populates="qualifications")


class Skill(ClaimMixin, Base):
    __tablename__ = "skills"
    __table_args__ = claim_checks("skills")
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="skills")


class Credential(ClaimMixin, Base):
    __tablename__ = "credentials"
    __table_args__ = (
        *claim_checks("credentials"),
        enum_check("verification_status", VerificationStatus, "ck_credentials_verification_status"),
        CheckConstraint(
            "verification_method IS NULL OR verification_method IN (" + ", ".join(f"'{m.value}'" for m in VerificationMethod) + ")",
            name="ck_credentials_verification_method",
        ),
        CheckConstraint(
            "expiration_date IS NULL OR issue_date IS NULL OR expiration_date >= issue_date",
            name="ck_credentials_dates_order",
        ),
        Index("ix_credentials_expiration", "organization_id", "expiration_date"),
    )
    type_code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(200))
    identifier: Mapped[str | None] = mapped_column(String(80))
    jurisdiction: Mapped[str | None] = mapped_column(String(80))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    expiration_text: Mapped[str | None] = mapped_column(String(60))
    verification_status: Mapped[str] = mapped_column(String(20), default=VerificationStatus.NOT_STARTED.value, nullable=False)
    verification_method: Mapped[str | None] = mapped_column(String(30))
    verification_reference: Mapped[str | None] = mapped_column(String(300))
    verified_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)

    candidate: Mapped[Candidate] = relationship(back_populates="credentials")


class CandidateNote(Base):
    __tablename__ = "candidate_notes"
    __table_args__ = (
        enum_check("kind", NoteKind, "ck_candidate_notes_kind"),
        CheckConstraint(
            "decision IS NULL OR decision IN (" + ", ".join(f"'{d.value}'" for d in Decision) + ")",
            name="ck_candidate_notes_decision",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="notes")
    author: Mapped[User | None] = relationship()


class OnboardingTemplateTask(Base):
    __tablename__ = "onboarding_template_tasks"
    __table_args__ = (
        enum_check("kind", TaskKind, "ck_onboarding_template_tasks_kind"),
        enum_check("owner_role", Role, "ck_onboarding_template_tasks_owner_role"),
        CheckConstraint("due_offset_days >= 0", name="ck_onboarding_template_tasks_due_offset"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default=TaskKind.MANUAL.value, nullable=False)
    owner_role: Mapped[str] = mapped_column(String(20), default=Role.RECRUITER.value, nullable=False)
    due_offset_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OnboardingTask(TimestampMixin, Base):
    __tablename__ = "onboarding_tasks"
    __table_args__ = (
        enum_check("kind", TaskKind, "ck_onboarding_tasks_kind"),
        enum_check("status", TaskStatus, "ck_onboarding_tasks_status"),
        # Instantiating the template twice for a candidate must not duplicate tasks.
        UniqueConstraint("candidate_id", "template_task_id", name="uq_onboarding_tasks_candidate_template"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    template_task_id: Mapped[str | None] = mapped_column(ForeignKey("onboarding_template_tasks.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.TODO.value, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    waived_reason: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    candidate: Mapped[Candidate] = relationship(back_populates="tasks")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])


class AuditEvent(Base):
    """Append-only audit log. There is intentionally no update/delete API."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_org_created", "organization_id", "created_at"),
        Index("ix_audit_events_candidate", "candidate_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_label: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
