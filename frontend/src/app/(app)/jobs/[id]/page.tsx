"use client";

import { ChevronDown, ChevronRight, Pencil } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { MatchBreakdown } from "@/components/match";
import { useSession } from "@/components/session";
import { CandidateStatusBadge, EligibilityBadge, ScoreBar } from "@/components/status";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingBlock, PageHeader, useToast } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { JobMatches } from "@/lib/types";

type Row = JobMatches["results"][number];

function MatchRow({ row, rank, jobId, onAssigned }: { row: Row; rank: number; jobId: string; onAssigned: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const m = row.match;
  const topAction = m.next_actions[0]?.label;

  async function assign() {
    setBusy(true);
    try {
      await api.patch(`/candidates/${row.candidate.id}`, { job_id: jobId });
      toast(`${row.candidate.full_name} assigned to this role.`);
      onAssigned();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not assign.", "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li>
      <div className="grid items-center gap-x-3 gap-y-2 px-4 py-3 md:grid-cols-[1.5rem_minmax(0,1fr)_auto_6.5rem_auto]">
        <span className="text-sm tabular-nums text-slate-400">{rank}</span>
        <div className="min-w-0">
          <Link href={`/candidates/${row.candidate.id}`} className="text-sm font-medium text-slate-900 hover:underline">
            {row.candidate.full_name}
          </Link>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <CandidateStatusBadge value={row.candidate.status} />
            {row.candidate.assigned_to_this_job ? <Badge tone="neutral" icon={false}>Applied to this role</Badge> : <Badge tone="muted" icon={false}>Not assigned</Badge>}
          </div>
        </div>
        <EligibilityBadge value={m.eligibility} />
        <ScoreBar score={m.score} eligibility={m.eligibility} />
        <div className="flex justify-end gap-1.5">
          {!row.candidate.assigned_to_this_job && can("manage_candidates") && (
            <Button size="sm" onClick={assign} loading={busy}>
              Assign
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />} Why?
          </Button>
        </div>
        <p className="text-xs text-slate-600 md:col-span-4 md:col-start-2">
          {m.satisfied} met · {m.pending} pending · {m.unknown} unknown · {m.not_satisfied} not met
          {topAction && <span className="text-slate-500"> — Next: {topAction}</span>}
        </p>
      </div>
      {open && (
        <div className="border-t border-slate-100 bg-slate-50/60 px-4 py-4">
          <MatchBreakdown match={m} compact />
        </div>
      )}
    </li>
  );
}

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useSession();
  const [scope, setScope] = useState<"all" | "assigned">("all");
  const { data, error, mutate } = useSWR<JobMatches>(`/job-roles/${id}/matches?scope=${scope}`, fetcher, { keepPreviousData: true });

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <LoadingBlock rows={8} />;
  const job = data.job;

  return (
    <>
      <PageHeader
        back={{ href: "/jobs", label: "Job roles" }}
        title={job.title}
        description={[job.department, job.location, job.status === "closed" ? "Closed" : "Open"].filter(Boolean).join(" · ")}
        actions={
          can("manage_jobs") && (
            <Link href={`/jobs/${job.id}/edit`} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3.5 text-sm font-medium text-slate-800 hover:bg-slate-50">
              <Pencil className="size-4" aria-hidden /> Edit requirements
            </Link>
          )
        }
      />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Requirements" description="Required items gate eligibility; weights only order candidates." className="xl:col-span-1">
          {job.description && <p className="mb-3 text-sm text-slate-700">{job.description}</p>}
          <ul className="space-y-2">
            {job.requirements.map((r) => (
              <li key={r.id} className="flex items-start justify-between gap-2 text-sm">
                <span className="text-slate-800">
                  {r.label}
                  <span className="block text-xs text-slate-500">
                    {titleCase(r.kind)}
                    {r.min_valid_days ? ` · must remain valid ≥ ${r.min_valid_days} days` : ""}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  <Badge tone={r.is_required ? "neutral" : "muted"} icon={false}>
                    {r.is_required ? "Required" : "Preferred"}
                  </Badge>
                  <span className="text-xs tabular-nums text-slate-500" title="Weight">
                    ×{r.weight}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
        <Card
          className="xl:col-span-2"
          title="Ranked candidates"
          description="Ordered by eligibility tier, then weighted score. This is decision support for a person — no one is rejected automatically."
          actions={
            <div role="group" aria-label="Candidate scope" className="inline-flex rounded-md border border-slate-300 p-0.5 text-xs">
              {(["all", "assigned"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setScope(s)}
                  aria-pressed={scope === s}
                  className={`rounded px-2.5 py-1 font-medium ${scope === s ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
                >
                  {s === "all" ? "All active candidates" : "Assigned to this role"}
                </button>
              ))}
            </div>
          }
          bodyClassName="p-0"
        >
          {data.results.length === 0 ? (
            <div className="p-4">
              <EmptyState title="No candidates to rank">{scope === "assigned" ? "No candidates are assigned to this role yet." : "Add candidates to see how they match."}</EmptyState>
            </div>
          ) : (
            <ol className="divide-y divide-slate-100">
              {data.results.map((row, i) => (
                <MatchRow key={row.candidate.id} row={row} rank={i + 1} jobId={job.id} onAssigned={() => mutate()} />
              ))}
            </ol>
          )}
        </Card>
      </div>
    </>
  );
}
