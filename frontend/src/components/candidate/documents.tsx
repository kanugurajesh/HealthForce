"use client";

import { Download, FileSearch, RotateCw, Upload } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useRef, useState } from "react";
import { useSession } from "@/components/session";
import { JobStateBadge } from "@/components/status";
import { ApiErrorMessage, Badge, Button, Callout, Card, EmptyState, Field, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { bytes, formatDateTime } from "@/lib/format";
import type { CandidateDetail, DocumentSummary } from "@/lib/types";

function UploadForm({ c, onUploaded }: { c: CandidateDetail; onUploaded: () => void }) {
  const { meta } = useSession();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState("resume");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    if (file.size > meta.max_upload_mb * 1024 * 1024) {
      setError(new Error(`The file is larger than ${meta.max_upload_mb} MB.`));
      return;
    }
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    try {
      const res = await api.post<{ created: boolean }>(`/candidates/${c.id}/documents`, form);
      toast(res.created ? "Uploaded. Extraction is running in the background." : "This exact file was already uploaded — nothing new was queued.", res.created ? "success" : "warning");
      if (fileRef.current) fileRef.current.value = "";
      onUploaded();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-3 md:grid-cols-[1fr_12rem_auto] md:items-end">
      <Field label="Document" htmlFor="up-file" hint={`PDF with a text layer, .txt or .md, up to ${meta.max_upload_mb} MB. Scanned images are not supported (no OCR).`}>
        <input
          id="up-file"
          ref={fileRef}
          type="file"
          accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
          required
          className="block w-full text-sm text-slate-700 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-200"
        />
      </Field>
      <Field label="Document type" htmlFor="up-kind">
        <Select id="up-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="resume">Resume / CV</option>
          <option value="credential">License or certification</option>
          <option value="other">Other</option>
        </Select>
      </Field>
      <Button type="submit" variant="primary" loading={busy}>
        <Upload className="size-4" aria-hidden /> Upload
      </Button>
      <div className="md:col-span-3">
        <ApiErrorMessage error={error} />
      </div>
    </form>
  );
}

function DocumentRow({ d, onChanged }: { d: DocumentSummary; onChanged: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const job = d.job;
  const counts = d.claim_counts;
  const extracted = ["credential", "experience", "qualification", "skill"].filter((k) => counts[k]).map((k) => `${counts[k]} ${k}${counts[k] > 1 ? "s" : ""}`);

  async function reprocess() {
    setBusy(true);
    try {
      await api.post(`/documents/${d.id}/process`);
      toast(job?.status === "failed" ? "Retry queued." : "Re-extraction queued. Reviewed items are kept.");
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not queue processing.", "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="space-y-2 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/documents/${d.id}`} className="text-sm font-semibold text-slate-900 hover:text-brand-700 hover:underline">
            {d.original_filename}
          </Link>
          <p className="text-xs text-slate-500">
            {d.kind === "resume" ? "Resume" : d.kind === "credential" ? "Credential document" : "Other"} · {bytes(d.size_bytes)} · uploaded {formatDateTime(d.created_at)}
            {d.uploaded_by_name ? ` by ${d.uploaded_by_name}` : ""}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {job && <JobStateBadge value={job.status} />}
            {job && <Badge tone="muted" icon={false}>{job.provider === "mock" ? "Mock extractor" : job.provider === "groq" ? "gpt-oss-120b (Groq)" : job.provider}</Badge>}
            {d.injection_suspected && <Badge tone="warning">Instruction-like text detected</Badge>}
            {counts.unreviewed ? <Badge tone="info">{counts.unreviewed} to review</Badge> : null}
            {extracted.length > 0 && <span className="text-xs text-slate-500">{extracted.join(", ")}</span>}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Link href={`/documents/${d.id}`} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 text-xs font-medium text-slate-800 hover:bg-slate-50">
            <FileSearch className="size-3.5" aria-hidden /> Review evidence
          </Link>
          <a href={`/api/documents/${d.id}/file`} className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-slate-700 hover:bg-slate-100">
            <Download className="size-3.5" aria-hidden /> Original
          </a>
          {can("upload_documents") && job && (job.status === "failed" || job.status === "succeeded") && (
            <Button size="sm" variant={job.status === "failed" ? "primary" : "ghost"} onClick={reprocess} loading={busy}>
              <RotateCw className="size-3.5" aria-hidden /> {job.status === "failed" ? "Retry" : "Re-extract"}
            </Button>
          )}
        </div>
      </div>
      {job?.status === "failed" && (
        <Callout tone="danger" title={`Processing failed after ${job.attempts} attempt(s)`}>
          {job.last_error}
          {!job.retryable && " Retrying will not help unless the file changes — upload a different version or add the details manually."}
        </Callout>
      )}
      {job?.status === "pending" && job.attempts > 0 && (
        <Callout tone="warning" title={`Attempt ${job.attempts} of ${job.max_attempts} failed; retrying automatically`}>
          {job.last_error}
        </Callout>
      )}
      {job?.status === "succeeded" && job.warnings.length > 0 && (
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer font-medium">{job.warnings.length} processing note(s)</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {job.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

export function DocumentsTab({ c, refresh }: { c: CandidateDetail; refresh: () => void }) {
  const { can } = useSession();
  return (
    <div className="space-y-4">
      {can("upload_documents") && (
        <Card title="Upload a document" description="Files are validated, stored under a random name, and processed in the background. Contact details are redacted before extraction.">
          <UploadForm c={c} onUploaded={refresh} />
        </Card>
      )}
      <Card title="Documents" bodyClassName="p-0">
        {c.documents.length === 0 ? (
          <div className="p-4">
            <EmptyState title="No documents yet">Upload a resume and the candidate&apos;s license and certification documents.</EmptyState>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {c.documents.map((d) => (
              <DocumentRow key={d.id} d={d} onChanged={refresh} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
