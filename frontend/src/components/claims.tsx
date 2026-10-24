"use client";

import { Check, FileSearch, Pencil, ShieldCheck, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { type FormEvent, type ReactNode, useState } from "react";
import { useSession } from "@/components/session";
import { ReviewBadge } from "@/components/status";
import { ApiErrorMessage, Badge, Button, Dialog, Field, Input, Select, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime, SOURCE_LABEL, titleCase } from "@/lib/format";
import type { CandidateDetail, ClaimBase, ClaimKind, Credential, Experience, Qualification, Skill } from "@/lib/types";

type OnChanged = (detail: CandidateDetail) => void;

export function EvidenceQuote({ claim }: { claim: ClaimBase }) {
  if (claim.source === "manual") {
    return <p className="text-xs italic text-slate-500">Entered manually{claim.review_note ? ` — source: ${claim.review_note}` : ""}.</p>;
  }
  return (
    <figure className="rounded-md border-l-2 border-amber-400 bg-amber-50/60 px-3 py-2">
      <blockquote className="whitespace-pre-line font-mono text-xs leading-relaxed text-slate-800">{claim.evidence_quote ?? "(no quote)"}</blockquote>
      <figcaption className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <span>{SOURCE_LABEL[claim.source]}</span>
        {claim.evidence_status === "found" ? (
          <span className="text-emerald-700">Quote located in the source document</span>
        ) : (
          <span className="font-medium text-amber-700">Quote NOT found in the source — treat as unsupported</span>
        )}
        {claim.document_id && (
          <Link href={`/documents/${claim.document_id}?claim=${claim.id}`} className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
            <FileSearch className="size-3.5" aria-hidden /> View in document
          </Link>
        )}
      </figcaption>
    </figure>
  );
}

export function Flags({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return (
    <ul className="space-y-1">
      {flags.map((f, i) => (
        <li key={i} className="flex gap-1.5 text-xs text-amber-800">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{f}</span>
        </li>
      ))}
    </ul>
  );
}

export function ReviewMeta({ claim }: { claim: ClaimBase }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
      <ReviewBadge value={claim.review_state} />
      {claim.reviewed_by_name && (
        <span>
          by {claim.reviewed_by_name} · {formatDateTime(claim.reviewed_at)}
        </span>
      )}
      {claim.review_note && claim.source !== "manual" && <span className="italic">“{claim.review_note}”</span>}
    </div>
  );
}

/** Accept / reject / correct controls for any claim. Hidden for users without review permission. */
export function ClaimActions({ kind, claim, onChanged }: { kind: ClaimKind; claim: Credential | Experience | Qualification | Skill; onChanged: OnChanged }) {
  const { can } = useSession();
  const toast = useToast();
  const [dialog, setDialog] = useState<"reject" | "correct" | "accept-note" | null>(null);
  const [busy, setBusy] = useState(false);
  if (!can("review_claims")) return null;

  async function accept() {
    if (claim.evidence_status === "not_found") {
      setDialog("accept-note");
      return;
    }
    setBusy(true);
    try {
      onChanged(await api.post<CandidateDetail>(`/claims/${kind}/${claim.id}/review`, { action: "accept" }));
      toast("Accepted.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not accept.", "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {claim.review_state !== "accepted" && claim.review_state !== "corrected" && (
        <Button size="sm" onClick={accept} loading={busy}>
          <Check className="size-3.5" aria-hidden /> Accept
        </Button>
      )}
      <Button size="sm" onClick={() => setDialog("correct")}>
        <Pencil className="size-3.5" aria-hidden /> Correct
      </Button>
      {claim.review_state !== "rejected" && (
        <Button size="sm" variant="ghost" onClick={() => setDialog("reject")}>
          <X className="size-3.5" aria-hidden /> Reject
        </Button>
      )}
      <ReasonDialog
        open={dialog === "reject" || dialog === "accept-note"}
        title={dialog === "reject" ? "Reject extracted item" : "Accept item without located evidence"}
        description={
          dialog === "reject"
            ? "Rejected items are ignored by matching and credential rules. The reason is kept in the audit trail."
            : "The quoted evidence could not be found in the document. Explain how you confirmed this item."
        }
        confirmLabel={dialog === "reject" ? "Reject" : "Accept"}
        danger={dialog === "reject"}
        onClose={() => setDialog(null)}
        onSubmit={async (note) => {
          onChanged(await api.post<CandidateDetail>(`/claims/${kind}/${claim.id}/review`, { action: dialog === "reject" ? "reject" : "accept", note }));
          toast(dialog === "reject" ? "Rejected." : "Accepted.");
        }}
      />
      {dialog === "correct" && <CorrectDialog kind={kind} claim={claim} onClose={() => setDialog(null)} onChanged={onChanged} />}
    </div>
  );
}

export function ReasonDialog({ open, title, description, confirmLabel, danger, onClose, onSubmit, required = true, children }: {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  required?: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => Promise<void>;
  children?: ReactNode;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(reason.trim());
      setReason("");
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="reason-form" variant={danger ? "danger" : "primary"} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <form id="reason-form" onSubmit={submit} className="space-y-3">
        {children}
        <Field label={required ? "Reason" : "Reason (optional)"} htmlFor="reason" required={required}>
          <Textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} required={required} maxLength={1000} />
        </Field>
        <ApiErrorMessage error={error} />
      </form>
    </Dialog>
  );
}

function CorrectDialog({ kind, claim, onClose, onChanged }: { kind: ClaimKind; claim: Credential | Experience | Qualification | Skill; onClose: () => void; onChanged: OnChanged }) {
  const { meta } = useSession();
  const toast = useToast();
  const initial: Record<string, unknown> =
    kind === "credentials"
      ? pick(claim, ["type_code", "issuer", "identifier", "jurisdiction", "issue_date", "expiration_date"])
      : kind === "experiences"
        ? pick(claim, ["title", "employer", "start_date", "end_date", "is_current", "settings"])
        : kind === "qualifications"
          ? pick(claim, ["code", "institution", "completion_year"])
          : pick(claim, ["code", "name"]);
  const [values, setValues] = useState<Record<string, unknown>>(initial);
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: unknown) => setValues((s) => ({ ...s, [k]: v }));
  const text = (k: string, label: string, type = "text") => (
    <Field label={label} htmlFor={`f-${k}`}>
      <Input id={`f-${k}`} type={type} value={(values[k] as string | number | null) ?? ""} onChange={(e) => set(k, e.target.value === "" ? null : type === "number" ? Number(e.target.value) : e.target.value)} />
    </Field>
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    const changed = Object.fromEntries(Object.entries(values).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(initial[k])));
    if (Object.keys(changed).length === 0) {
      setError(new Error("Change at least one field."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.patch<CandidateDetail>(`/claims/${kind}/${claim.id}`, { ...changed, note: note.trim() || null }));
      toast("Correction saved.");
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
      title="Correct extracted data"
      description="Your correction replaces the extracted value and is recorded, with the previous value, in the audit trail."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="correct-form" variant="primary" loading={busy}>
            Save correction
          </Button>
        </>
      }
    >
      <form id="correct-form" onSubmit={submit} className="space-y-4">
        {claim.evidence_quote && (
          <div>
            <p className="mb-1 text-xs font-medium text-slate-700">Source evidence</p>
            <EvidenceQuote claim={claim} />
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          {kind === "credentials" && (
            <>
              <Field label="Credential type" htmlFor="f-type">
                <Select id="f-type" value={values.type_code as string} onChange={(e) => set("type_code", e.target.value)}>
                  {meta.credential_types.map((t) => (
                    <option key={t.code} value={t.code}>
                      {t.label}
                    </option>
                  ))}
                  <option value="OTHER">Other</option>
                </Select>
              </Field>
              {text("issuer", "Issuing organization")}
              {text("identifier", "Credential number")}
              {text("jurisdiction", "Jurisdiction / state")}
              {text("issue_date", "Issue date", "date")}
              {text("expiration_date", "Expiration date", "date")}
            </>
          )}
          {kind === "experiences" && (
            <>
              {text("title", "Title")}
              {text("employer", "Employer")}
              {text("start_date", "Start date", "date")}
              {text("end_date", "End date", "date")}
              <label className="flex items-center gap-2 text-sm sm:col-span-2">
                <input type="checkbox" checked={Boolean(values.is_current)} onChange={(e) => set("is_current", e.target.checked)} /> Current role
              </label>
              <fieldset className="sm:col-span-2">
                <legend className="mb-1 text-xs font-medium text-slate-700">Care settings (used for experience requirements)</legend>
                <div className="flex flex-wrap gap-3">
                  {meta.experience_settings.map((s) => {
                    const list = (values.settings as string[]) ?? [];
                    return (
                      <label key={s} className="flex items-center gap-1.5 text-sm">
                        <input type="checkbox" checked={list.includes(s)} onChange={(e) => set("settings", e.target.checked ? [...list, s] : list.filter((x) => x !== s))} />
                        {titleCase(s)}
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            </>
          )}
          {kind === "qualifications" && (
            <>
              <Field label="Qualification" htmlFor="f-code">
                <Select id="f-code" value={values.code as string} onChange={(e) => set("code", e.target.value)}>
                  {meta.qualifications.map((q) => (
                    <option key={q.code} value={q.code}>
                      {q.label}
                    </option>
                  ))}
                  <option value="OTHER">Other</option>
                </Select>
              </Field>
              {text("institution", "Institution")}
              {text("completion_year", "Completion year", "number")}
            </>
          )}
          {kind === "skills" && (
            <>
              <Field label="Skill" htmlFor="f-code">
                <Select id="f-code" value={values.code as string} onChange={(e) => set("code", e.target.value)}>
                  {meta.skills.map((s) => (
                    <option key={s.code} value={s.code}>
                      {s.label}
                    </option>
                  ))}
                  <option value="other">Other (free text)</option>
                </Select>
              </Field>
              {text("name", "Name as written")}
            </>
          )}
        </div>
        <Field label="Note (what you checked)" htmlFor="f-note">
          <Textarea id="f-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} placeholder="e.g. Confirmed on the license lookup printout" />
        </Field>
        {kind === "credentials" && (claim as Credential).verification_status !== "not_started" && (
          <p className="text-xs text-amber-800">Changing the type, number, jurisdiction or dates resets the existing verification.</p>
        )}
        <ApiErrorMessage error={error} />
      </form>
    </Dialog>
  );
}

function pick(obj: object, keys: string[]): Record<string, unknown> {
  return Object.fromEntries(keys.map((k) => [k, (obj as Record<string, unknown>)[k] ?? null]));
}

export function VerifyDialog({ credential, onClose, onChanged }: { credential: Credential; onClose: () => void; onChanged: OnChanged }) {
  const { meta } = useSession();
  const toast = useToast();
  const simulatedAllowed = meta.verification_mode === "simulated";
  const [method, setMethod] = useState<"manual_primary_source" | "simulated">("manual_primary_source");
  const [outcome, setOutcome] = useState<"verified" | "failed">("verified");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const source = meta.credential_types.find((t) => t.code === credential.type_code)?.verification_source;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = method === "simulated" ? { outcome: "verified", method } : { outcome, method, reference: reference.trim() };
      onChanged(await api.post<CandidateDetail>(`/credentials/${credential.id}/verification`, body));
      toast(method === "simulated" ? "Simulated verification recorded." : `Verification recorded (${outcome}).`);
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
      title={`Record verification — ${credential.type_label}`}
      description="Verification is a separate fact from review. This system does not contact any registry; record what you checked."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="verify-form" variant="primary" loading={busy}>
            <ShieldCheck className="size-4" aria-hidden /> Record
          </Button>
        </>
      }
    >
      <form id="verify-form" onSubmit={submit} className="space-y-3">
        {source && <p className="text-xs text-slate-600">Primary source for this credential: {source}.</p>}
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium text-slate-700">Method</legend>
          <label className="flex items-start gap-2 text-sm">
            <input type="radio" name="method" checked={method === "manual_primary_source"} onChange={() => setMethod("manual_primary_source")} className="mt-1" />
            <span>
              <span className="font-medium">Manual primary-source check</span>
              <span className="block text-xs text-slate-500">You looked the credential up with the issuer or board yourself.</span>
            </span>
          </label>
          <label className={`flex items-start gap-2 text-sm ${simulatedAllowed ? "" : "opacity-50"}`}>
            <input type="radio" name="method" disabled={!simulatedAllowed} checked={method === "simulated"} onChange={() => setMethod("simulated")} className="mt-1" />
            <span>
              <span className="font-medium">Simulated (demo only)</span>
              <span className="block text-xs text-slate-500">Marks the credential verified with a SIMULATED label. No registry is contacted.</span>
            </span>
          </label>
        </fieldset>
        {method === "manual_primary_source" && (
          <>
            <Field label="Outcome" htmlFor="v-outcome">
              <Select id="v-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as "verified" | "failed")}>
                <option value="verified">Verified — matches the primary source</option>
                <option value="failed">Failed — could not be confirmed / does not match</option>
              </Select>
            </Field>
            <Field label="Reference" htmlFor="v-ref" required hint="Where and when you checked, e.g. “State board lookup 2026-10-23, record matches”.">
              <Input id="v-ref" value={reference} onChange={(e) => setReference(e.target.value)} required maxLength={300} />
            </Field>
          </>
        )}
        <ApiErrorMessage error={error} />
      </form>
    </Dialog>
  );
}

export function SourceBadge({ source }: { source: ClaimBase["source"] }) {
  return (
    <Badge tone={source === "manual" ? "neutral" : "muted"} icon={false}>
      {SOURCE_LABEL[source]}
    </Badge>
  );
}
