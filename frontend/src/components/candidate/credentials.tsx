"use client";

import { Plus, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { ClaimActions, EvidenceQuote, Flags, ReviewMeta, SourceBadge, VerifyDialog } from "@/components/claims";
import { useSession } from "@/components/session";
import { CredentialStatusBadge } from "@/components/status";
import { ApiErrorMessage, Badge, Button, Callout, Dialog, EmptyState, Field, Input, KeyValue, Select, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, formatDateTime, relativeDays } from "@/lib/format";
import type { CandidateDetail, Credential, CredentialStatus } from "@/lib/types";

const RANK: Record<CredentialStatus, number> = {
  verified: 0,
  expiring_soon: 1,
  pending_verification: 2,
  pending_review: 3,
  unable_to_determine: 4,
  expired: 5,
  rejected: 6,
  missing: 7,
};

function VerificationLine({ c }: { c: Credential }) {
  if (c.verification_status === "not_started") return <span className="text-slate-500">Not verified</span>;
  const who = c.verified_by_name ? ` by ${c.verified_by_name}` : "";
  if (c.verification_status === "failed") return <span className="text-red-700">Failed{who} · {formatDateTime(c.verified_at)}</span>;
  return (
    <span className={c.simulated_verification ? "text-amber-800" : "text-emerald-800"}>
      {c.simulated_verification ? "SIMULATED verification (demo — no registry contacted)" : "Primary-source check recorded"}
      {who} · {formatDateTime(c.verified_at)}
    </span>
  );
}

function CredentialRecord({ c, onChanged, primary }: { c: Credential; onChanged: (d: CandidateDetail) => void; primary: boolean }) {
  const { can } = useSession();
  const [verifying, setVerifying] = useState(false);
  const canVerify = can("verify_credentials") && (c.review_state === "accepted" || c.review_state === "corrected");
  return (
    <div className={`space-y-3 p-4 ${primary ? "" : "bg-slate-50/60"}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <CredentialStatusBadge status={c.status} simulated={c.simulated_verification} />
          <SourceBadge source={c.source} />
          {!primary && <span className="text-xs text-slate-500">Additional record</span>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <ClaimActions kind="credentials" claim={c} onChanged={onChanged} />
          {canVerify && (
            <Button size="sm" onClick={() => setVerifying(true)}>
              <ShieldCheck className="size-3.5" aria-hidden /> Verify
            </Button>
          )}
        </div>
      </div>
      <ul className="space-y-0.5 text-sm text-slate-700">
        {c.status_reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
      <div className="grid gap-4 md:grid-cols-2">
        <KeyValue
          items={[
            ["Name as written", c.name],
            ["Number", c.identifier],
            ["Issuer", c.issuer],
            ["Jurisdiction", c.jurisdiction],
            ["Issued", formatDate(c.issue_date)],
            [
              "Expires",
              c.expiration_date ? (
                <>
                  {formatDate(c.expiration_date)}
                  {c.days_until_expiry !== null && <span className="text-xs text-slate-500"> ({relativeDays(c.days_until_expiry)})</span>}
                  {c.expiration_text && <span className="block text-xs text-slate-500">printed as “{c.expiration_text}”</span>}
                </>
              ) : (
                <span className="text-amber-700">Not established</span>
              ),
            ],
            ["Verification", <VerificationLine key="v" c={c} />],
            ...(c.verification_reference ? ([["Reference", c.verification_reference]] as [string, string][]) : []),
          ]}
        />
        <div className="space-y-2">
          <EvidenceQuote claim={c} />
          <Flags flags={c.flags} />
          <ReviewMeta claim={c} />
        </div>
      </div>
      {verifying && <VerifyDialog credential={c} onClose={() => setVerifying(false)} onChanged={onChanged} />}
    </div>
  );
}

function AddCredentialDialog({ c, onClose, onChanged }: { c: CandidateDetail; onClose: () => void; onChanged: (d: CandidateDetail) => void }) {
  const { meta } = useSession();
  const toast = useToast();
  const [form, setForm] = useState({ type_code: meta.credential_types[0].code, issuer: "", identifier: "", jurisdiction: "", issue_date: "", expiration_date: "", note: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]));
      onChanged(await api.post<CandidateDetail>(`/candidates/${c.id}/credentials`, body));
      toast("Credential added. Record a verification when checked.");
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
      size="lg"
      onClose={onClose}
      title="Add credential manually"
      description="Use this when a document cannot be processed (e.g. a scanned image). The entry is attributed to you and starts unverified."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="add-cred" variant="primary" loading={busy}>
            Add credential
          </Button>
        </>
      }
    >
      <form id="add-cred" onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <Field label="Credential type" htmlFor="ac-type" required>
          <Select id="ac-type" value={form.type_code} onChange={set("type_code")}>
            {meta.credential_types.map((t) => (
              <option key={t.code} value={t.code}>
                {t.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Credential number" htmlFor="ac-id">
          <Input id="ac-id" value={form.identifier} onChange={set("identifier")} />
        </Field>
        <Field label="Issuing organization" htmlFor="ac-iss">
          <Input id="ac-iss" value={form.issuer} onChange={set("issuer")} />
        </Field>
        <Field label="Jurisdiction / state" htmlFor="ac-jur">
          <Input id="ac-jur" value={form.jurisdiction} onChange={set("jurisdiction")} />
        </Field>
        <Field label="Issue date" htmlFor="ac-issue">
          <Input id="ac-issue" type="date" value={form.issue_date} onChange={set("issue_date")} />
        </Field>
        <Field label="Expiration date" htmlFor="ac-exp" hint="Leave empty if unknown — the credential will show as “unable to determine”.">
          <Input id="ac-exp" type="date" value={form.expiration_date} onChange={set("expiration_date")} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Source of this information" htmlFor="ac-note" required>
            <Textarea id="ac-note" value={form.note} onChange={set("note")} required minLength={3} placeholder="e.g. Read from the paper certificate presented in person on 10/23" />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <ApiErrorMessage error={error} />
        </div>
      </form>
    </Dialog>
  );
}

export function CredentialsTab({ c, onChanged }: { c: CandidateDetail; onChanged: (d: CandidateDetail) => void }) {
  const { can } = useSession();
  const [adding, setAdding] = useState(false);
  const groups = new Map<string, Credential[]>();
  for (const cred of c.credentials) groups.set(cred.type_code, [...(groups.get(cred.type_code) ?? []), cred]);
  const sorted = [...groups.entries()].map(([code, records]) => {
    const selfReported = (c: Credential) => (c.status_reasons.some((r) => r.startsWith("Self-reported")) ? 1 : 0);
    const ordered = [...records].sort(
      (a, b) => RANK[a.status] - RANK[b.status] || (b.expiration_date ?? "").localeCompare(a.expiration_date ?? "") || selfReported(a) - selfReported(b),
    );
    return { code, records: ordered, best: ordered[0] };
  });
  sorted.sort((a, b) => RANK[b.best.status] - RANK[a.best.status]);
  const missing = c.missing_credentials;

  return (
    <div className="space-y-4">
      <Callout tone="info">
        Each credential keeps four separate facts: what was extracted, a reviewer&apos;s decision, verification, and expiration. Status follows a fixed precedence:{" "}
        <span className="font-medium">rejected › conflicting records › expired › no expiration date › pending review › pending verification › expiring soon › verified</span>.
      </Callout>
      {missing.length > 0 && (
        <Callout tone="danger" title="Required by the job role but not on file">
          {missing.join("; ")}. This is missing information — request the document; it is not treated as a failed requirement.
        </Callout>
      )}
      {can("review_claims") && (
        <div className="flex justify-end">
          <Button onClick={() => setAdding(true)}>
            <Plus className="size-4" aria-hidden /> Add credential manually
          </Button>
        </div>
      )}
      {sorted.length === 0 ? (
        <EmptyState title="No credentials on file">Upload license or certification documents on the Documents tab.</EmptyState>
      ) : (
        sorted.map(({ code, records, best }) => (
          <section key={code} className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-white px-4 py-3">
              <h3 className="text-sm font-semibold text-slate-900">{best.type_label}</h3>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">Status used for matching:</span>
                <CredentialStatusBadge status={best.status} simulated={best.simulated_verification} />
                {records.length > 1 && <Badge tone="neutral" icon={false}>{records.length} records</Badge>}
              </div>
            </header>
            <div className="divide-y divide-slate-100">
              {records.map((r, i) => (
                <CredentialRecord key={r.id} c={r} onChanged={onChanged} primary={i === 0} />
              ))}
            </div>
          </section>
        ))
      )}
      {adding && <AddCredentialDialog c={c} onClose={() => setAdding(false)} onChanged={onChanged} />}
    </div>
  );
}
