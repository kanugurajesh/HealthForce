/** Mirrors backend/app/schemas.py output models. */

export type Role = "admin" | "recruiter" | "reviewer" | "viewer";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  organization: { id: string; name: string };
  permissions: string[];
}

export interface Meta {
  as_of: string;
  extraction_provider: { name: string; is_mock: boolean; misconfigured: boolean; label: string };
  verification_mode: "disabled" | "simulated";
  expiring_soon_days: number;
  max_upload_mb: number;
  credential_types: { code: string; label: string; expires: boolean; verification_source: string }[];
  qualifications: { code: string; label: string }[];
  skills: { code: string; label: string }[];
  experience_settings: string[];
  experience_requirement_settings: string[];
  candidate_statuses: string[];
  transitions: Record<string, string[]>;
  users: { id: string; full_name: string; role: Role }[];
}

export interface ClaimBase {
  id: string;
  document_id: string | null;
  source: "ai" | "mock" | "manual";
  evidence_quote: string | null;
  evidence_start: number | null;
  evidence_end: number | null;
  evidence_status: "found" | "not_found" | "none";
  review_state: "unreviewed" | "accepted" | "corrected" | "rejected";
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  flags: string[];
  created_at: string;
  updated_at: string;
}

export interface Experience extends ClaimBase {
  title: string;
  employer: string | null;
  settings: string[];
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  start_text: string | null;
  end_text: string | null;
  description: string | null;
  duration_years: number | null;
}

export interface Qualification extends ClaimBase {
  code: string;
  label: string;
  name: string;
  institution: string | null;
  completion_year: number | null;
}

export interface Skill extends ClaimBase {
  code: string;
  label: string;
  name: string;
}

export type CredentialStatus =
  | "missing"
  | "pending_review"
  | "pending_verification"
  | "verified"
  | "expiring_soon"
  | "expired"
  | "rejected"
  | "unable_to_determine";

export interface Credential extends ClaimBase {
  type_code: string;
  type_label: string;
  name: string;
  issuer: string | null;
  identifier: string | null;
  jurisdiction: string | null;
  issue_date: string | null;
  expiration_date: string | null;
  expiration_text: string | null;
  verification_status: "not_started" | "verified" | "failed";
  verification_method: "manual_primary_source" | "simulated" | null;
  verification_reference: string | null;
  verified_at: string | null;
  verified_by_name: string | null;
  status: CredentialStatus;
  status_reasons: string[];
  expiring_soon: boolean;
  days_until_expiry: number | null;
  simulated_verification: boolean;
  conflicts_with: string[];
}

export type ClaimKind = "experiences" | "qualifications" | "skills" | "credentials";

export interface EvidenceRef {
  claim_type: string;
  claim_id: string;
  document_id: string | null;
  quote: string | null;
  review_state: string;
  status: string | null;
}

export type Outcome = "met" | "pending" | "unknown" | "not_met";
export type Eligibility = "meets_all_required" | "pending" | "missing_information" | "requirement_not_met";

export interface RequirementResult {
  requirement_id: string;
  kind: "credential" | "qualification" | "skill" | "experience";
  label: string;
  is_required: boolean;
  weight: number;
  outcome: Outcome;
  explanation: string;
  points_earned: number;
  points_possible: number;
  next_action: string | null;
  evidence: EvidenceRef[];
}

export interface NextAction {
  priority: number;
  label: string;
  requirement_id: string | null;
}

export interface Match {
  job: { id: string; title: string };
  score: number;
  eligibility: Eligibility;
  eligibility_explanation: string;
  score_explanation: string;
  satisfied: number;
  not_satisfied: number;
  pending: number;
  unknown: number;
  requirements: RequirementResult[];
  next_actions: NextAction[];
}

export interface ProcessingJob {
  id: string;
  document_id: string;
  status: "pending" | "processing" | "succeeded" | "failed";
  provider: string;
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  last_error: string | null;
  retryable: boolean;
  warnings: string[];
  stats: Record<string, unknown>;
  next_attempt_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface DocumentSummary {
  id: string;
  candidate_id: string;
  kind: "resume" | "credential" | "other";
  original_filename: string;
  content_type: string;
  size_bytes: number;
  page_count: number | null;
  injection_suspected: boolean;
  injection_signals: string[];
  created_at: string;
  uploaded_by_name: string | null;
  job: ProcessingJob | null;
  claim_counts: Record<string, number>;
}

export interface DocumentDetail extends DocumentSummary {
  candidate_name: string;
  text: string | null;
  experiences: Experience[];
  qualifications: Qualification[];
  skills: Skill[];
  credentials: Credential[];
}

export interface Task {
  id: string;
  title: string;
  description: string | null;
  kind: "manual" | "interview" | "credential_check" | "final_review";
  owner_role: Role;
  owner: { id: string; full_name: string; role: Role } | null;
  status: "todo" | "in_progress" | "done" | "waived";
  due_date: string | null;
  overdue: boolean;
  notes: string | null;
  completed_by_name: string | null;
  completed_at: string | null;
  waived_reason: string | null;
  blockers: string[];
  position: number;
}

export interface Note {
  id: string;
  kind: "note" | "decision";
  decision: "advance" | "hold" | "decline" | null;
  body: string;
  author_name: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  actor_label: string;
  entity_type: string;
  entity_id: string;
  candidate_id: string | null;
  candidate_name: string | null;
  action: string;
  summary: string;
  reason: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface CandidateListItem {
  id: string;
  full_name: string;
  headline: string | null;
  location: string | null;
  status: string;
  job: { id: string; title: string } | null;
  eligibility: Eligibility | null;
  score: number | null;
  credential_statuses: CredentialStatus[];
  missing_credentials: string[];
  unreviewed_claims: number;
  flagged_claims: number;
  nearest_expiration: { date: string; type_code: string; type_label: string; days: number } | null;
  next_action: string | null;
  tasks_total: number;
  tasks_done: number;
  updated_at: string;
}

export interface CandidateDetail extends CandidateListItem {
  email: string | null;
  summary: string | null;
  summary_source: string | null;
  summary_reviewed: boolean;
  allowed_transitions: string[];
  experiences: Experience[];
  qualifications: Qualification[];
  skills: Skill[];
  credentials: Credential[];
  documents: DocumentSummary[];
  match: Match | null;
  next_actions: NextAction[];
  tasks: Task[];
  notes: Note[];
  clearance_blockers: string[];
  created_at: string;
}

export interface Requirement {
  id: string;
  kind: "credential" | "qualification" | "skill" | "experience";
  codes: string[];
  label: string;
  is_required: boolean;
  weight: number;
  min_years: number | null;
  setting: string | null;
  min_valid_days: number | null;
  position: number;
}

export interface JobRole {
  id: string;
  title: string;
  department: string | null;
  location: string | null;
  description: string | null;
  status: "open" | "closed";
  requirements: Requirement[];
  candidate_count: number;
  created_at: string;
  updated_at: string;
}

export interface JobMatches {
  job: JobRole;
  results: { candidate: { id: string; full_name: string; status: string; headline: string | null; assigned_to_this_job: boolean }; match: Match }[];
}

export interface ProcessingJobRow extends ProcessingJob {
  document_filename: string;
  document_kind: string;
  candidate_id: string;
  candidate_name: string;
}

export interface Dashboard {
  as_of: string;
  metrics: {
    total_candidates: number;
    active_candidates: number;
    awaiting_review: number;
    credential_issues: number;
    ready_for_next_step: number;
    in_onboarding: number;
    cleared: number;
    failed_jobs: number;
    queued_jobs: number;
  };
  pipeline: { status: string; count: number }[];
  upcoming_expirations: {
    candidate_id: string;
    candidate_name: string;
    credential_id: string;
    type_code: string;
    type_label: string;
    expiration_date: string;
    days_until_expiry: number;
    status: CredentialStatus;
  }[];
  next_actions: { candidate_id: string; candidate_name: string; label: string; priority: number }[];
  recent_activity: AuditEvent[];
}

export interface TemplateTask {
  id: string;
  title: string;
  description: string | null;
  kind: Task["kind"];
  owner_role: Role;
  due_offset_days: number;
  position: number;
}
