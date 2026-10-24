import type { CredentialStatus, Eligibility, Outcome } from "./types";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "muted";

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  // Backend timestamps are UTC without an offset.
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function relativeDays(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${-days} days ago`;
}

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export const CREDENTIAL_STATUS: Record<CredentialStatus, { label: string; tone: Tone; description: string }> = {
  verified: { label: "Verified", tone: "success", description: "Reviewed and verified; in date." },
  expiring_soon: { label: "Expiring soon", tone: "warning", description: "Verified, but expires within the warning window." },
  pending_verification: { label: "Pending verification", tone: "info", description: "Reviewed; not yet verified with a primary source." },
  pending_review: { label: "Pending review", tone: "info", description: "Extracted data has not been reviewed by a person." },
  unable_to_determine: { label: "Unable to determine", tone: "warning", description: "Expiration is unknown or records conflict." },
  expired: { label: "Expired", tone: "danger", description: "The expiration date has passed." },
  rejected: { label: "Rejected", tone: "danger", description: "Rejected or invalidated by a reviewer." },
  missing: { label: "Missing", tone: "danger", description: "A required credential is not on file." },
};

export const ELIGIBILITY: Record<Eligibility, { label: string; tone: Tone }> = {
  meets_all_required: { label: "Meets all required", tone: "success" },
  pending: { label: "Pending review", tone: "info" },
  missing_information: { label: "Missing information", tone: "warning" },
  requirement_not_met: { label: "Requirement not met", tone: "danger" },
};

export const OUTCOME: Record<Outcome, { label: string; tone: Tone }> = {
  met: { label: "Met", tone: "success" },
  pending: { label: "Pending", tone: "info" },
  unknown: { label: "Unknown", tone: "warning" },
  not_met: { label: "Not met", tone: "danger" },
};

export const CANDIDATE_STATUS: Record<string, { label: string; tone: Tone }> = {
  new: { label: "New", tone: "neutral" },
  screening: { label: "Screening", tone: "info" },
  interview: { label: "Interview", tone: "info" },
  offer: { label: "Offer", tone: "info" },
  onboarding: { label: "Onboarding", tone: "warning" },
  cleared: { label: "Cleared to start", tone: "success" },
  withdrawn: { label: "Withdrawn", tone: "muted" },
  not_selected: { label: "Not selected", tone: "muted" },
};

export const REVIEW_STATE: Record<string, { label: string; tone: Tone }> = {
  unreviewed: { label: "Unreviewed", tone: "info" },
  accepted: { label: "Accepted", tone: "success" },
  corrected: { label: "Corrected", tone: "success" },
  rejected: { label: "Rejected", tone: "muted" },
};

export const JOB_STATE: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Queued", tone: "info" },
  processing: { label: "Processing", tone: "info" },
  succeeded: { label: "Succeeded", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
};

export const SOURCE_LABEL: Record<string, string> = {
  ai: "AI-extracted",
  mock: "Mock-extracted",
  manual: "Entered manually",
};
