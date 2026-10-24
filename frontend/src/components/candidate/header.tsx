"use client";

import { ArrowRight, Pencil } from "lucide-react";
import { type FormEvent, useState } from "react";
import useSWR from "swr";
import { useSession } from "@/components/session";
import { CandidateStatusBadge, EligibilityBadge } from "@/components/status";
import { ApiErrorMessage, Button, Callout, Dialog, Field, Input, Select, Textarea, useToast } from "@/components/ui";
import { ApiError, api, fetcher } from "@/lib/api";
import { CANDIDATE_STATUS } from "@/lib/format";
import type { CandidateDetail, JobRole } from "@/lib/types";

const NEEDS_REASON = new Set(["withdrawn", "not_selected"]);

function StatusDialog({ c, onClose, onChanged }: { c: CandidateDetail; onClose: () => void; onChanged: (d: CandidateDetail) => void }) {
  const toast = useToast();
  const [target, setTarget] = useState(c.allowed_transitions[0] ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const forwardWithUnmet = c.eligibility === "requirement_not_met" && ["interview", "offer", "onboarding"].includes(target);
  const reasonRequired = NEEDS_REASON.has(target) || ["withdrawn", "not_selected", "cleared"].includes(c.status) || forwardWithUnmet;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.post<CandidateDetail>(`/candidates/${c.id}/status`, { status: target, reason: reason.trim() || null }));
      toast(`Moved to ${CANDIDATE_STATUS[target]?.label ?? target}.`);
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Change recruitment stage"
      description={`Currently: ${CANDIDATE_STATUS[c.status]?.label ?? c.status}. Every change is recorded in the activity log.`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="status-form" variant="primary" loading={busy} disabled={!target}>
            Confirm change
          </Button>
        </>
      }
    >
      <form id="status-form" onSubmit={submit} className="space-y-3">
        <Field label="New stage" htmlFor="st-target">
          <Select id="st-target" value={target} onChange={(e) => setTarget(e.target.value)}>
            {c.allowed_transitions.map((s) => (
              <option key={s} value={s}>
                {CANDIDATE_STATUS[s]?.label ?? s}
              </option>
            ))}
          </Select>
        </Field>
        {forwardWithUnmet && (
          <Callout tone="danger" title="A required requirement is not met">
            {c.match?.eligibility_explanation} You can still proceed — this is decision support, not an automatic rejection — but you must record why.
          </Callout>
        )}
        {target === "onboarding" && <Callout tone="info">The organization&apos;s onboarding checklist will be created for this candidate.</Callout>}
        {target === "cleared" && c.clearance_blockers.length > 0 && (
          <Callout tone="warning" title="Not ready to clear">
            <ul className="list-disc pl-4">
              {c.clearance_blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </Callout>
        )}
        <Field label={reasonRequired ? "Reason" : "Reason (optional)"} htmlFor="st-reason" required={reasonRequired}>
          <Textarea id="st-reason" value={reason} onChange={(e) => setReason(e.target.value)} required={reasonRequired} maxLength={1000} />
        </Field>
        <ApiErrorMessage error={error} />
      </form>
    </Dialog>
  );
}

function EditDialog({ c, onClose, onChanged }: { c: CandidateDetail; onClose: () => void; onChanged: (d: CandidateDetail) => void }) {
  const toast = useToast();
  const jobs = useSWR<JobRole[]>("/job-roles", fetcher);
  const [form, setForm] = useState({ full_name: c.full_name, email: c.email ?? "", headline: c.headline ?? "", location: c.location ?? "", job_id: c.job?.id ?? "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]));
      onChanged(await api.patch<CandidateDetail>(`/candidates/${c.id}`, body));
      toast("Candidate updated.");
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Edit candidate"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="edit-form" variant="primary" loading={busy}>
            Save
          </Button>
        </>
      }
    >
      <form id="edit-form" onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Full name" htmlFor="e-name" required>
            <Input id="e-name" value={form.full_name} onChange={set("full_name")} required />
          </Field>
        </div>
        <Field label="Email" htmlFor="e-email">
          <Input id="e-email" type="email" value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Location" htmlFor="e-loc">
          <Input id="e-loc" value={form.location} onChange={set("location")} />
        </Field>
        <Field label="Headline" htmlFor="e-head">
          <Input id="e-head" value={form.headline} onChange={set("headline")} />
        </Field>
        <Field label="Job role" htmlFor="e-job" hint="Matching and onboarding blockers use this role's requirements.">
          <Select id="e-job" value={form.job_id} onChange={set("job_id")}>
            <option value="">Not assigned</option>
            {(jobs.data ?? []).map((j) => (
              <option key={j.id} value={j.id}>
                {j.title}
                {j.status === "closed" ? " (closed)" : ""}
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

export function CandidateHeader({ c, onChanged }: { c: CandidateDetail; onChanged: (d: CandidateDetail) => void }) {
  const { can } = useSession();
  const [dialog, setDialog] = useState<"status" | "edit" | null>(null);
  return (
    <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight text-slate-900">{c.full_name}</h1>
            <CandidateStatusBadge value={c.status} />
          </div>
          <p className="mt-0.5 text-sm text-slate-600">{[c.headline, c.location, c.email].filter(Boolean).join(" · ") || "No profile details"}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-slate-500">Job role:</span>
            <span className="font-medium text-slate-800">{c.job?.title ?? "Not assigned"}</span>
            <EligibilityBadge value={c.eligibility} />
            {c.score !== null && <span className="text-xs text-slate-500">Score {c.score}/100</span>}
          </div>
        </div>
        {can("manage_candidates") && (
          <div className="flex gap-2">
            <Button onClick={() => setDialog("edit")}>
              <Pencil className="size-4" aria-hidden /> Edit
            </Button>
            {c.allowed_transitions.length > 0 && (
              <Button variant="primary" onClick={() => setDialog("status")}>
                Change stage <ArrowRight className="size-4" aria-hidden />
              </Button>
            )}
          </div>
        )}
      </div>
      {dialog === "status" && <StatusDialog c={c} onClose={() => setDialog(null)} onChanged={onChanged} />}
      {dialog === "edit" && <EditDialog c={c} onClose={() => setDialog(null)} onChanged={onChanged} />}
    </div>
  );
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}
