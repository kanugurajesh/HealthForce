"use client";

import { CheckCheck, Download, RotateCw } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { ClaimActions, Flags, ReviewMeta, SourceBadge } from "@/components/claims";
import { useSession } from "@/components/session";
import { CredentialStatusBadge, JobStateBadge } from "@/components/status";
import { Badge, Button, Callout, Card, ErrorState, LoadingBlock, PageHeader, useToast } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { formatDate, formatDateTime, titleCase } from "@/lib/format";
import type { ClaimBase, ClaimKind, Credential, DocumentDetail, Experience, Qualification, Skill } from "@/lib/types";

type AnyClaim = (Credential | Experience | Qualification | Skill) & { _kind: ClaimKind };

function label(c: AnyClaim): string {
  if (c._kind === "credentials") return (c as Credential).type_label;
  if (c._kind === "experiences") return (c as Experience).title;
  if (c._kind === "qualifications") return (c as Qualification).code === "OTHER" ? (c as Qualification).name : (c as Qualification).label;
  return (c as Skill).label;
}

function details(c: AnyClaim): string | null {
  if (c._kind === "credentials") {
    const x = c as Credential;
    return [x.identifier && `No. ${x.identifier}`, x.jurisdiction, x.expiration_date ? `expires ${formatDate(x.expiration_date)}` : "expiration not established"].filter(Boolean).join(" · ");
  }
  if (c._kind === "experiences") {
    const x = c as Experience;
    return [x.employer, `${x.start_date ? formatDate(x.start_date) : "?"} – ${x.is_current ? "present" : x.end_date ? formatDate(x.end_date) : "?"}`, x.settings.map(titleCase).join(", ")].filter(Boolean).join(" · ");
  }
  if (c._kind === "qualifications") {
    const x = c as Qualification;
    return [x.institution, x.completion_year].filter(Boolean).join(" · ") || null;
  }
  return null;
}

/** Splits the text at every evidence boundary and wraps covered segments in <mark>. */
function HighlightedText({ text, claims, active, onSelect }: { text: string; claims: AnyClaim[]; active: string | null; onSelect: (id: string) => void }) {
  const segments = useMemo(() => {
    const spans = claims.filter((c) => c.evidence_start !== null && c.evidence_end !== null && c.review_state !== "rejected");
    const cuts = new Set<number>([0, text.length]);
    spans.forEach((s) => {
      cuts.add(s.evidence_start!);
      cuts.add(s.evidence_end!);
    });
    const points = [...cuts].sort((a, b) => a - b);
    const firstMark = new Set<string>();
    return points.slice(0, -1).map((start, i) => {
      const end = points[i + 1];
      const covering = spans.filter((s) => s.evidence_start! <= start && s.evidence_end! >= end).map((s) => s.id);
      const anchors = covering.filter((id) => !firstMark.has(id));
      anchors.forEach((id) => firstMark.add(id));
      return { start, end, covering, anchors };
    });
  }, [text, claims]);

  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-slate-800">
      {segments.map((s) =>
        s.covering.length === 0 ? (
          <Fragment key={s.start}>{text.slice(s.start, s.end)}</Fragment>
        ) : (
          <mark
            key={s.start}
            id={s.anchors.length ? `ev-${s.anchors[0]}` : undefined}
            className={`evidence cursor-pointer ${active && s.covering.includes(active) ? "evidence-active" : ""}`}
            onClick={() => onSelect(s.covering[s.covering.length - 1])}
            title={`Evidence for ${s.covering.length} extracted item(s) — click to select`}
          >
            {text.slice(s.start, s.end)}
          </mark>
        ),
      )}
    </pre>
  );
}

function DocumentView() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const { can } = useSession();
  const toast = useToast();
  const [active, setActive] = useState<string | null>(params.get("claim"));
  const [busy, setBusy] = useState(false);
  const { data, error, mutate } = useSWR<DocumentDetail>(`/documents/${id}`, fetcher, {
    refreshInterval: (d) => (d?.job && (d.job.status === "pending" || d.job.status === "processing") ? 2000 : 0),
  });

  useEffect(() => {
    if (!active || !data) return;
    document.getElementById(`ev-${active}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active, data]);

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <LoadingBlock rows={10} />;

  const claims: AnyClaim[] = [
    ...data.credentials.map((c) => ({ ...c, _kind: "credentials" as const })),
    ...data.experiences.map((c) => ({ ...c, _kind: "experiences" as const })),
    ...data.qualifications.map((c) => ({ ...c, _kind: "qualifications" as const })),
    ...data.skills.map((c) => ({ ...c, _kind: "skills" as const })),
  ];
  const supported = claims.filter((c) => c.review_state === "unreviewed" && c.evidence_status === "found" && c.flags.length === 0).length;
  const job = data.job;

  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    try {
      await action();
      toast(message);
      await mutate();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        back={{ href: `/candidates/${data.candidate_id}?tab=documents`, label: data.candidate_name }}
        title={data.original_filename}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {job && <JobStateBadge value={job.status} />}
            <span>{data.kind === "resume" ? "Resume" : data.kind === "credential" ? "Credential document" : "Other document"}</span>
            {job && <span className="text-slate-500">· {job.provider === "mock" ? "Mock extractor (not AI)" : job.provider === "groq" ? "Extracted by gpt-oss-120b (Groq)" : job.provider}</span>}
            {job?.finished_at && <span className="text-slate-500">· {formatDateTime(job.finished_at)}</span>}
          </span>
        }
        actions={
          <>
            <a href={`/api/documents/${data.id}/file`} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3.5 text-sm font-medium text-slate-800 hover:bg-slate-50">
              <Download className="size-4" aria-hidden /> Original file
            </a>
            {can("upload_documents") && job && (job.status === "failed" || job.status === "succeeded") && (
              <Button onClick={() => run(() => api.post(`/documents/${data.id}/process`), job.status === "failed" ? "Retry queued." : "Re-extraction queued; reviewed items are kept.")} loading={busy}>
                <RotateCw className="size-4" aria-hidden /> {job.status === "failed" ? "Retry" : "Re-extract"}
              </Button>
            )}
            {can("review_claims") && supported > 0 && !data.injection_suspected && (
              <Button variant="primary" onClick={() => run(() => api.post(`/documents/${data.id}/accept-supported`), `Accepted ${supported} item(s).`)} loading={busy}>
                <CheckCheck className="size-4" aria-hidden /> Accept {supported} evidence-supported item(s)
              </Button>
            )}
          </>
        }
      />

      <div className="mb-4 space-y-2">
        {data.injection_suspected && (
          <Callout tone="warning" title="This document contains instruction-like text (possible prompt injection)">
            Signals: {data.injection_signals.join(", ")}. The text was treated purely as data — it cannot set statuses, verification or scores — but every value extracted from it must be checked individually. Bulk
            acceptance is disabled.
          </Callout>
        )}
        {job?.status === "failed" && (
          <Callout tone="danger" title={`Processing failed (${job.error_code})`}>
            {job.last_error}
          </Callout>
        )}
        {(job?.status === "pending" || job?.status === "processing") && <Callout tone="info">Extraction is in progress. This page refreshes automatically.</Callout>}
        {job?.status === "succeeded" && job.warnings.length > 0 && (
          <Callout tone="neutral" title="Processing notes">
            <ul className="list-disc space-y-0.5 pl-4 text-xs">
              {job.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Callout>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Document text" description="Extracted text as sent for extraction (contact details redacted). Highlights mark the evidence for each item." bodyClassName="max-h-[75vh] overflow-auto">
          {data.text ? <HighlightedText text={data.text} claims={claims} active={active} onSelect={setActive} /> : <p className="text-sm text-slate-500">No text available.</p>}
        </Card>
        <Card title={`Extracted items (${claims.length})`} description="Select an item to locate its evidence. Nothing here is used until a person reviews it." bodyClassName="max-h-[75vh] overflow-auto p-0">
          {claims.length === 0 ? (
            <p className="p-4 text-sm text-slate-500">{job?.status === "succeeded" ? "No relevant information was extracted from this document." : "No items yet."}</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {claims.map((c) => (
                <li
                  key={c.id}
                  className={`space-y-2 p-4 ${active === c.id ? "bg-amber-50/70" : ""} ${c.review_state === "rejected" ? "opacity-60" : ""}`}
                  onClick={(e) => {
                    if (!(e.target as HTMLElement).closest("button,a,select,input,textarea,dialog")) setActive(c.id);
                  }}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-slate-500">{c._kind.slice(0, -1)}</p>
                      <p className="text-sm font-semibold text-slate-900">{label(c)}</p>
                      {details(c) && <p className="text-xs text-slate-600">{details(c)}</p>}
                      <div className="mt-1 flex flex-wrap gap-1">
                        {c._kind === "credentials" && <CredentialStatusBadge status={(c as Credential).status} simulated={(c as Credential).simulated_verification} />}
                        <SourceBadge source={c.source} />
                        {c.evidence_status === "not_found" && <Badge tone="warning">Evidence not located</Badge>}
                      </div>
                    </div>
                    <ClaimActions kind={c._kind} claim={c} onChanged={() => mutate()} />
                  </div>
                  <button type="button" className="block w-full whitespace-pre-line rounded border-l-2 border-amber-400 bg-amber-50/60 px-2 py-1 text-left font-mono text-xs text-slate-700 hover:bg-amber-100/60" onClick={() => setActive(c.id)}>
                    {(c as ClaimBase).evidence_quote ?? "(no quote)"}
                  </button>
                  <Flags flags={c.flags} />
                  <ReviewMeta claim={c} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <p className="mt-4 text-xs text-slate-500">
        Need the full candidate context? <Link href={`/candidates/${data.candidate_id}`} className="font-medium text-brand-700 hover:underline">Open {data.candidate_name}</Link>.
      </p>
    </>
  );
}

export default function DocumentPage() {
  return (
    <Suspense fallback={<LoadingBlock rows={10} />}>
      <DocumentView />
    </Suspense>
  );
}
