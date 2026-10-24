"use client";

import Link from "next/link";
import { useState } from "react";
import { formatDateTime } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";

function Details({ details }: { details: Record<string, unknown> }) {
  const changes = (details.changes ?? null) as Record<string, { from: unknown; to: unknown }> | null;
  if (changes) {
    return (
      <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
        {Object.entries(changes).map(([field, v]) => (
          <li key={field}>
            <span className="font-medium">{field}</span>: <span className="line-through decoration-slate-400">{String(v.from ?? "—")}</span> → {String(v.to ?? "—")}
          </li>
        ))}
      </ul>
    );
  }
  const keys = Object.keys(details);
  if (!keys.length) return null;
  return <pre className="mt-1 max-h-40 overflow-auto rounded bg-slate-50 p-2 text-[11px] leading-snug text-slate-600">{JSON.stringify(details, null, 2)}</pre>;
}

function EventItem({ e, showCandidate }: { e: AuditEvent; showCandidate: boolean }) {
  const [open, setOpen] = useState(false);
  const hasDetails = Object.keys(e.details ?? {}).length > 0;
  return (
    <li className="relative pl-5">
      <span className="absolute left-0 top-1.5 size-2 rounded-full bg-slate-300" aria-hidden />
      <p className="text-sm text-slate-800">
        {e.summary}
        {showCandidate && e.candidate_id && e.candidate_name && (
          <>
            {" "}
            ·{" "}
            <Link href={`/candidates/${e.candidate_id}`} className="font-medium text-brand-700 hover:underline">
              {e.candidate_name}
            </Link>
          </>
        )}
      </p>
      {e.reason && <p className="text-xs italic text-slate-600">Reason: {e.reason}</p>}
      <p className="text-xs text-slate-500">
        {e.actor_label} · {formatDateTime(e.created_at)} · <code className="text-[11px]">{e.action}</code>
        {hasDetails && (
          <button className="ml-2 font-medium text-brand-700 hover:underline" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide details" : "Details"}
          </button>
        )}
      </p>
      {open && <Details details={e.details} />}
    </li>
  );
}

export function AuditList({ events, showCandidate = true }: { events: AuditEvent[]; showCandidate?: boolean }) {
  if (!events.length) return <p className="text-sm text-slate-500">No activity recorded.</p>;
  return (
    <ol className="space-y-3 border-l border-slate-200 pl-1">
      {events.map((e) => (
        <EventItem key={e.id} e={e} showCandidate={showCandidate} />
      ))}
    </ol>
  );
}
