import { Badge } from "@/components/ui";
import { CANDIDATE_STATUS, CREDENTIAL_STATUS, ELIGIBILITY, JOB_STATE, OUTCOME, REVIEW_STATE, titleCase } from "@/lib/format";
import type { CredentialStatus, Eligibility, Outcome } from "@/lib/types";

export function CredentialStatusBadge({ status, simulated }: { status: CredentialStatus; simulated?: boolean }) {
  const s = CREDENTIAL_STATUS[status] ?? { label: titleCase(status), tone: "neutral" as const, description: "" };
  return (
    <Badge tone={s.tone} title={s.description}>
      {s.label}
      {simulated && (status === "verified" || status === "expiring_soon") ? " (simulated)" : ""}
    </Badge>
  );
}

export function EligibilityBadge({ value }: { value: Eligibility | null }) {
  if (!value) return <Badge tone="muted">No job assigned</Badge>;
  const e = ELIGIBILITY[value];
  return <Badge tone={e.tone}>{e.label}</Badge>;
}

export function OutcomeBadge({ value }: { value: Outcome }) {
  const o = OUTCOME[value];
  return <Badge tone={o.tone}>{o.label}</Badge>;
}

export function CandidateStatusBadge({ value }: { value: string }) {
  const s = CANDIDATE_STATUS[value] ?? { label: titleCase(value), tone: "neutral" as const };
  return (
    <Badge tone={s.tone} icon={false}>
      {s.label}
    </Badge>
  );
}

export function ReviewBadge({ value }: { value: string }) {
  const s = REVIEW_STATE[value] ?? { label: titleCase(value), tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function JobStateBadge({ value }: { value: string }) {
  const s = JOB_STATE[value] ?? { label: titleCase(value), tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function ScoreBar({ score, eligibility }: { score: number; eligibility: Eligibility }) {
  const color = eligibility === "requirement_not_met" ? "bg-red-400" : eligibility === "meets_all_required" ? "bg-emerald-500" : "bg-sky-500";
  return (
    <div className="flex items-center gap-2" title={`Weighted score ${score}/100`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200" aria-hidden>
        <div className={`h-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-sm tabular-nums text-slate-700">
        {score}
        <span className="sr-only"> out of 100</span>
      </span>
    </div>
  );
}
