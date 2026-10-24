"use client";

import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { useSession } from "@/components/session";
import { CandidateStatusBadge, CredentialStatusBadge, EligibilityBadge, ScoreBar } from "@/components/status";
import { ApiErrorMessage, Badge, Button, Dialog, EmptyState, ErrorState, Field, Input, LoadingBlock, PageHeader, Select } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { CANDIDATE_STATUS, CREDENTIAL_STATUS, ELIGIBILITY, formatDate } from "@/lib/format";
import type { CandidateDetail, CandidateListItem, CredentialStatus, JobRole } from "@/lib/types";

const ACTIVE = "new,screening,interview,offer,onboarding,cleared";
const SEVERITY: CredentialStatus[] = ["missing", "expired", "rejected", "unable_to_determine", "expiring_soon", "pending_review", "pending_verification", "verified"];
const FILTER_KEYS = ["q", "status", "job_id", "credential_status", "eligibility", "review", "expiring_within"] as const;

function CreateCandidateDialog({ open, onClose, jobs }: { open: boolean; onClose: () => void; jobs: JobRole[] }) {
  const router = useRouter();
  const [form, setForm] = useState({ full_name: "", email: "", headline: "", location: "", job_id: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]));
      const c = await api.post<CandidateDetail>("/candidates", body);
      router.push(`/candidates/${c.id}?tab=documents`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add candidate"
      description="Collect only what is needed for recruitment. Do not enter patient information."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="create-candidate" loading={busy}>
            Create and upload documents
          </Button>
        </>
      }
    >
      <form id="create-candidate" onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Full name" htmlFor="c-name" required>
            <Input id="c-name" value={form.full_name} onChange={set("full_name")} required maxLength={200} autoFocus />
          </Field>
        </div>
        <Field label="Email" htmlFor="c-email">
          <Input id="c-email" type="email" value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Location" htmlFor="c-loc">
          <Input id="c-loc" value={form.location} onChange={set("location")} />
        </Field>
        <Field label="Headline" htmlFor="c-head">
          <Input id="c-head" value={form.headline} onChange={set("headline")} placeholder="e.g. ICU RN, 5 years" />
        </Field>
        <Field label="Job role" htmlFor="c-job">
          <Select id="c-job" value={form.job_id} onChange={set("job_id")}>
            <option value="">Not assigned yet</option>
            {jobs.filter((j) => j.status === "open").map((j) => (
              <option key={j.id} value={j.id}>
                {j.title}
              </option>
            ))}
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <ApiErrorMessage error={error} />
        </div>
      </form>
    </Dialog>
  );
}

function CredentialSummary({ item }: { item: CandidateListItem }) {
  const worst = SEVERITY.filter((s) => item.credential_statuses.includes(s));
  if (worst.length === 0) return <span className="text-xs text-slate-400">None on file</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {worst.slice(0, 2).map((s) => (
        <CredentialStatusBadge key={s} status={s} />
      ))}
      {worst.length > 2 && <Badge tone="neutral" icon={false}>+{worst.length - 2}</Badge>}
    </div>
  );
}

function CandidatesView() {
  const { can } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState(params.get("q") ?? "");

  const query = useMemo(() => {
    const p = new URLSearchParams();
    FILTER_KEYS.forEach((k) => {
      const v = params.get(k);
      if (v) p.set(k, v);
    });
    return p.toString();
  }, [params]);

  const { data, error, isLoading, mutate } = useSWR<{ items: CandidateListItem[]; total: number }>(`/candidates${query ? `?${query}` : ""}`, fetcher, { keepPreviousData: true });
  const jobs = useSWR<JobRole[]>("/job-roles", fetcher);

  function setFilter(key: string, value: string) {
    const p = new URLSearchParams(params.toString());
    if (value) p.set(key, value);
    else p.delete(key);
    router.replace(`${pathname}${p.toString() ? `?${p}` : ""}`);
  }

  useEffect(() => {
    const t = setTimeout(() => {
      if ((params.get("q") ?? "") !== search) setFilter("q", search.trim());
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const status = params.get("status") ?? "";
  const credentialStatus = params.get("credential_status") ?? "";
  const anyFilter = FILTER_KEYS.some((k) => params.get(k));

  return (
    <>
      <PageHeader
        title="Candidates"
        description="Readiness is computed from reviewed evidence and deterministic rules. Nothing here rejects a candidate automatically."
        actions={
          can("manage_candidates") && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden /> Add candidate
            </Button>
          )
        }
      />

      <div className="mb-4 grid gap-2 rounded-lg border border-slate-200 bg-white p-3 shadow-sm sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        <div className="relative sm:col-span-2 lg:col-span-1 xl:col-span-2">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-slate-400" aria-hidden />
          <Input aria-label="Search candidates" placeholder="Search name, headline, location" className="pl-8" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Select aria-label="Candidate status" value={status} onChange={(e) => setFilter("status", e.target.value)}>
          <option value="">All statuses</option>
          <option value={ACTIVE}>Active (excl. withdrawn / not selected)</option>
          {status && status !== ACTIVE && !CANDIDATE_STATUS[status] && <option value={status}>Custom: {status.replaceAll(",", ", ")}</option>}
          {Object.entries(CANDIDATE_STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Job role" value={params.get("job_id") ?? ""} onChange={(e) => setFilter("job_id", e.target.value)}>
          <option value="">All job roles</option>
          {(jobs.data ?? []).map((j) => (
            <option key={j.id} value={j.id}>
              {j.title}
            </option>
          ))}
        </Select>
        <Select aria-label="Credential status" value={credentialStatus} onChange={(e) => setFilter("credential_status", e.target.value)}>
          <option value="">Any credential status</option>
          <option value="missing,expired,rejected,unable_to_determine">Any credential issue</option>
          {credentialStatus.includes(",") && credentialStatus !== "missing,expired,rejected,unable_to_determine" && <option value={credentialStatus}>Custom</option>}
          {Object.entries(CREDENTIAL_STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Eligibility" value={params.get("eligibility") ?? ""} onChange={(e) => setFilter("eligibility", e.target.value)}>
          <option value="">Any eligibility</option>
          {Object.entries(ELIGIBILITY).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Review state" value={params.get("review") ?? ""} onChange={(e) => setFilter("review", e.target.value)}>
          <option value="">Any review state</option>
          <option value="needs_review">Needs review</option>
          <option value="flagged">Has flagged items</option>
          <option value="reviewed">Fully reviewed</option>
        </Select>
        <Select aria-label="Expiring within" value={params.get("expiring_within") ?? ""} onChange={(e) => setFilter("expiring_within", e.target.value)}>
          <option value="">Any expiration</option>
          <option value="30">Expiring within 30 days</option>
          <option value="60">Expiring within 60 days</option>
          <option value="90">Expiring within 90 days</option>
        </Select>
        {anyFilter && (
          <Button
            variant="ghost"
            onClick={() => {
              setSearch("");
              router.replace(pathname);
            }}
          >
            Clear filters
          </Button>
        )}
      </div>

      {error ? (
        <ErrorState error={error} retry={() => mutate()} />
      ) : isLoading && !data ? (
        <LoadingBlock rows={8} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState title={anyFilter ? "No candidates match these filters" : "No candidates yet"}>
          {anyFilter ? "Try removing a filter." : "Add a candidate and upload their resume and credential documents."}
        </EmptyState>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-4 py-2 text-xs text-slate-500" aria-live="polite">
            {data.total} candidate{data.total === 1 ? "" : "s"}
          </div>
          {/* Small screens: stacked cards instead of a wide table. */}
          <ul className="divide-y divide-slate-100 md:hidden">
            {data.items.map((c) => (
              <li key={c.id} className="space-y-2 px-4 py-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link href={`/candidates/${c.id}`} className="font-medium text-slate-900 hover:underline">
                      {c.full_name}
                    </Link>
                    <p className="text-xs text-slate-500">{c.job?.title ?? "No job role"}</p>
                  </div>
                  <CandidateStatusBadge value={c.status} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <EligibilityBadge value={c.eligibility} />
                  {c.score !== null && <span className="text-xs text-slate-500">Score {c.score}</span>}
                  <CredentialSummary item={c} />
                </div>
                {c.next_action && <p className="text-xs text-slate-600">Next: {c.next_action}</p>}
              </li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Candidate</th>
                  <th scope="col" className="px-4 py-2 font-medium">Stage</th>
                  <th scope="col" className="px-4 py-2 font-medium">Job role & eligibility</th>
                  <th scope="col" className="px-4 py-2 font-medium">Score</th>
                  <th scope="col" className="px-4 py-2 font-medium">Credentials</th>
                  <th scope="col" className="px-4 py-2 font-medium">Review</th>
                  <th scope="col" className="px-4 py-2 font-medium">Next action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((c) => (
                  <tr key={c.id} className="align-top hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <Link href={`/candidates/${c.id}`} className="font-medium text-slate-900 hover:text-brand-700 hover:underline">
                        {c.full_name}
                      </Link>
                      <p className="text-xs text-slate-500">{[c.headline, c.location].filter(Boolean).join(" · ")}</p>
                    </td>
                    <td className="px-4 py-3">
                      <CandidateStatusBadge value={c.status} />
                      {c.tasks_total > 0 && (
                        <p className="mt-1 text-xs text-slate-500">
                          Onboarding {c.tasks_done}/{c.tasks_total}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <p className="mb-1 text-xs text-slate-600">{c.job?.title ?? "—"}</p>
                      <EligibilityBadge value={c.eligibility} />
                    </td>
                    <td className="px-4 py-3">{c.score !== null && c.eligibility ? <ScoreBar score={c.score} eligibility={c.eligibility} /> : <span className="text-slate-400">—</span>}</td>
                    <td className="px-4 py-3">
                      <CredentialSummary item={c} />
                      {c.nearest_expiration && c.nearest_expiration.days <= 90 && (
                        <p className="mt-1 text-xs text-slate-500">
                          Next expiry: {c.nearest_expiration.type_code.replace("_", " ")} {formatDate(c.nearest_expiration.date)}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {c.unreviewed_claims > 0 ? (
                        <Badge tone={c.flagged_claims ? "warning" : "info"}>
                          {c.unreviewed_claims} to review{c.flagged_claims ? `, ${c.flagged_claims} flagged` : ""}
                        </Badge>
                      ) : (
                        <Badge tone="success">Reviewed</Badge>
                      )}
                    </td>
                    <td className="max-w-xs px-4 py-3 text-xs text-slate-600">{c.next_action ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <CreateCandidateDialog open={creating} onClose={() => setCreating(false)} jobs={jobs.data ?? []} />
    </>
  );
}

export default function CandidatesPage() {
  return (
    <Suspense fallback={<LoadingBlock rows={8} />}>
      <CandidatesView />
    </Suspense>
  );
}
