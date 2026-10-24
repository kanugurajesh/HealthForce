"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { useSession } from "@/components/session";
import { Badge, EmptyState, ErrorState, LoadingBlock, PageHeader } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { JobRole } from "@/lib/types";

export default function JobsPage() {
  const { can } = useSession();
  const { data, error, mutate } = useSWR<JobRole[]>("/job-roles", fetcher);
  return (
    <>
      <PageHeader
        title="Job roles"
        description="Requirements are evaluated deterministically against reviewed candidate evidence."
        actions={
          can("manage_jobs") && (
            <Link href="/jobs/new" className="inline-flex h-9 items-center gap-1.5 rounded-md bg-brand-600 px-3.5 text-sm font-medium text-white hover:bg-brand-700">
              <Plus className="size-4" aria-hidden /> New job role
            </Link>
          )
        }
      />
      {error ? (
        <ErrorState error={error} retry={() => mutate()} />
      ) : !data ? (
        <LoadingBlock />
      ) : data.length === 0 ? (
        <EmptyState title="No job roles yet">Create a role and its requirements to start matching candidates.</EmptyState>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.map((j) => {
            const required = j.requirements.filter((r) => r.is_required);
            return (
              <Link key={j.id} href={`/jobs/${j.id}`} className="block rounded-lg border border-slate-200 bg-white p-4 shadow-sm hover:border-slate-300">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="text-sm font-semibold text-slate-900">{j.title}</h2>
                  <Badge tone={j.status === "open" ? "success" : "muted"}>{j.status === "open" ? "Open" : "Closed"}</Badge>
                </div>
                <p className="mt-0.5 text-xs text-slate-500">{[j.department, j.location].filter(Boolean).join(" · ") || "—"}</p>
                <p className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">Required</p>
                <ul className="mt-1 space-y-0.5 text-sm text-slate-700">
                  {required.slice(0, 4).map((r) => (
                    <li key={r.id} className="truncate">
                      • {r.label}
                    </li>
                  ))}
                  {required.length > 4 && <li className="text-xs text-slate-500">+{required.length - 4} more</li>}
                </ul>
                <p className="mt-3 text-xs text-slate-500">
                  {j.requirements.length - required.length} preferred · {j.candidate_count} candidate(s) assigned
                </p>
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}
