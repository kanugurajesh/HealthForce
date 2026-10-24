"use client";

import Link from "next/link";
import useSWR from "swr";
import { CredentialStatusBadge } from "@/components/status";
import { Callout, Card, EmptyState, ErrorState, LoadingBlock, PageHeader, Stat } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { CANDIDATE_STATUS, formatDate, formatDateTime, relativeDays } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

// Same scopes the backend uses for each metric, so a tile and the list it opens always agree.
const ACTIVE = "new,screening,interview,offer,onboarding,cleared";

export default function DashboardPage() {
  const { data, error, mutate, isLoading } = useSWR<Dashboard>("/dashboard", fetcher, { refreshInterval: 15000 });

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (isLoading || !data) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <LoadingBlock rows={6} />
      </>
    );
  }
  const m = data.metrics;
  const maxPipeline = Math.max(1, ...data.pipeline.map((p) => p.count));

  return (
    <>
      <PageHeader title="Dashboard" description={`Recruitment and credential readiness as of ${formatDate(data.as_of)}.`} />

      {m.total_candidates === 0 ? (
        <EmptyState title="No candidates yet" action={<Link className="text-sm font-medium text-brand-700 hover:underline" href="/candidates">Add a candidate</Link>}>
          Create a candidate and upload a resume to see readiness metrics here.
        </EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Candidates" value={m.total_candidates} hint={`${m.active_candidates} active`} href="/candidates" />
            <Stat label="Awaiting review" value={m.awaiting_review} hint="Unreviewed extracted data" href={`/candidates?review=needs_review&status=${ACTIVE}`} tone="info" />
            <Stat label="Credential issues" value={m.credential_issues} hint="Missing, expired, rejected or undetermined" href={`/candidates?credential_status=missing,expired,rejected,unable_to_determine&status=${ACTIVE}`} tone="danger" />
            <Stat label="Ready for next step" value={m.ready_for_next_step} hint="Meet every required requirement" href="/candidates?eligibility=meets_all_required&status=new,screening,interview,offer" tone="success" />
            <Stat label="In onboarding" value={m.in_onboarding} hint={`${m.cleared} cleared to start`} href="/candidates?status=onboarding" tone="warning" />
            <Stat label="Processing failures" value={m.failed_jobs} hint={`${m.queued_jobs} queued`} href="/processing?status=failed" tone={m.failed_jobs ? "danger" : "neutral"} />
          </div>

          {m.failed_jobs > 0 && (
            <div className="mt-4">
              <Callout tone="danger" title={`${m.failed_jobs} document(s) could not be processed`}>
                Review the failures on the <Link href="/processing?status=failed" className="font-medium underline">document processing</Link> page — retry them or enter the details manually.
              </Callout>
            </div>
          )}

          <div className="mt-6 grid gap-4 lg:grid-cols-3">
            <Card title="Recommended next actions" description="The most urgent step for each active candidate" className="lg:col-span-2" bodyClassName="p-0">
              {data.next_actions.length === 0 ? (
                <p className="p-4 text-sm text-slate-500">Nothing needs attention right now.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {data.next_actions.map((a) => (
                    <li key={a.candidate_id}>
                      <Link href={`/candidates/${a.candidate_id}`} className="flex items-start justify-between gap-4 px-4 py-3 hover:bg-slate-50">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-900">{a.candidate_name}</p>
                          <p className="text-sm text-slate-600">{a.label}</p>
                        </div>
                        <span className="shrink-0 text-xs text-brand-700">Open →</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Pipeline" description="Candidates by recruitment stage">
              <ul className="space-y-2">
                {data.pipeline.map((p) => (
                  <li key={p.status}>
                    <Link href={`/candidates?status=${p.status}`} className="group grid grid-cols-[7.5rem_1fr_2rem] items-center gap-2 text-sm">
                      <span className="text-slate-600 group-hover:text-slate-900">{CANDIDATE_STATUS[p.status]?.label ?? p.status}</span>
                      <span className="h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden>
                        <span className="block h-full rounded-full bg-brand-500" style={{ width: `${(p.count / maxPipeline) * 100}%` }} />
                      </span>
                      <span className="text-right tabular-nums text-slate-900">{p.count}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="Credential expirations" description="Expired in the last 30 days or expiring within the warning window" className="lg:col-span-2" bodyClassName="p-0">
              {data.upcoming_expirations.length === 0 ? (
                <p className="p-4 text-sm text-slate-500">No credentials expire in the warning window.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        <th scope="col" className="px-4 py-2 font-medium">Candidate</th>
                        <th scope="col" className="px-4 py-2 font-medium">Credential</th>
                        <th scope="col" className="px-4 py-2 font-medium">Expires</th>
                        <th scope="col" className="px-4 py-2 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {data.upcoming_expirations.map((e) => (
                        <tr key={e.credential_id}>
                          <td className="px-4 py-2">
                            <Link href={`/candidates/${e.candidate_id}`} className="font-medium text-slate-900 hover:underline">
                              {e.candidate_name}
                            </Link>
                          </td>
                          <td className="px-4 py-2 text-slate-700">{e.type_label}</td>
                          <td className="px-4 py-2 text-slate-700">
                            {formatDate(e.expiration_date)} <span className="text-xs text-slate-500">({relativeDays(e.days_until_expiry)})</span>
                          </td>
                          <td className="px-4 py-2">
                            <CredentialStatusBadge status={e.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            <Card title="Recent activity" actions={<Link href="/activity" className="text-xs font-medium text-brand-700 hover:underline">View all</Link>} bodyClassName="p-0">
              <ul className="divide-y divide-slate-100">
                {data.recent_activity.map((e) => (
                  <li key={e.id} className="px-4 py-2.5">
                    <p className="text-sm text-slate-800">{e.summary}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {e.actor_label} · {formatDateTime(e.created_at)}
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
