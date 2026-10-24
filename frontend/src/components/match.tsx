"use client";

import { ChevronDown, ChevronRight, FileSearch } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { EligibilityBadge, OutcomeBadge } from "@/components/status";
import { Badge, Callout } from "@/components/ui";
import type { Match, RequirementResult } from "@/lib/types";

/** "Why does the system believe this?" — every requirement with outcome, points and evidence. */
export function MatchBreakdown({ match, compact = false }: { match: Match; compact?: boolean }) {
  const required = match.requirements.filter((r) => r.is_required);
  const preferred = match.requirements.filter((r) => !r.is_required);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Eligibility (required only)</p>
          <div className="mt-1">
            <EligibilityBadge value={match.eligibility} />
          </div>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Weighted score</p>
          <p className="mt-0.5 text-lg font-semibold tabular-nums">
            {match.score}
            <span className="text-sm font-normal text-slate-500">/100</span>
          </p>
        </div>
        <p className="text-xs text-slate-600">
          {match.satisfied} met · {match.pending} pending · {match.unknown} unknown · {match.not_satisfied} not met
        </p>
      </div>
      <Callout tone={match.eligibility === "meets_all_required" ? "success" : match.eligibility === "requirement_not_met" ? "danger" : "warning"}>
        {match.eligibility_explanation}
      </Callout>
      <RequirementTable title="Required" rows={required} compact={compact} />
      {preferred.length > 0 && <RequirementTable title="Preferred" rows={preferred} compact={compact} />}
      <details className="text-xs text-slate-600">
        <summary className="cursor-pointer font-medium text-slate-700">How is the score calculated?</summary>
        <p className="mt-1">{match.score_explanation}</p>
      </details>
    </div>
  );
}

function RequirementTable({ title, rows, compact }: { title: string; rows: RequirementResult[]; compact: boolean }) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
        {rows.map((r) => (
          <RequirementRow key={r.requirement_id} r={r} compact={compact} />
        ))}
      </ul>
    </div>
  );
}

function RequirementRow({ r, compact }: { r: RequirementResult; compact: boolean }) {
  const [open, setOpen] = useState(!compact && r.outcome !== "met");
  const quotes = r.evidence.filter((e) => e.quote);
  return (
    <li className="px-3 py-2">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-2 text-left">
        {open ? <ChevronDown className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden /> : <ChevronRight className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />}
        <span className="min-w-0 flex-1 text-sm font-medium text-slate-900">{r.label}</span>
        <span className="hidden text-xs tabular-nums text-slate-500 sm:inline" title="Points earned / possible">
          {r.points_earned}/{r.points_possible} pts
        </span>
        <OutcomeBadge value={r.outcome} />
      </button>
      {open && (
        <div className="ml-6 mt-2 space-y-2 text-sm">
          <p className="text-slate-700">{r.explanation}</p>
          {r.next_action && <p className="text-xs font-medium text-brand-800">Next step: {r.next_action}</p>}
          {r.evidence.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-slate-500">Evidence considered</p>
              {r.evidence.map((e) => (
                <div key={e.claim_id} className="flex flex-wrap items-start gap-2 rounded bg-slate-50 px-2 py-1.5 text-xs">
                  <Badge tone="neutral" icon={false}>
                    {e.claim_type}
                  </Badge>
                  {e.status && <Badge tone="muted" icon={false}>{e.status.replace(/_/g, " ")}</Badge>}
                  <Badge tone={e.review_state === "unreviewed" ? "info" : e.review_state === "rejected" ? "muted" : "success"} icon={false}>
                    {e.review_state}
                  </Badge>
                  {e.quote && <span className="min-w-0 flex-1 truncate font-mono text-slate-700" title={e.quote}>“{e.quote.split("\n")[0]}”</span>}
                  {e.document_id && (
                    <Link href={`/documents/${e.document_id}?claim=${e.claim_id}`} className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
                      <FileSearch className="size-3.5" aria-hidden /> source
                    </Link>
                  )}
                </div>
              ))}
              {quotes.length === 0 && r.evidence.some((e) => e.claim_type === "credential") && (
                <p className="text-xs text-slate-500">Credential records are listed on the Credentials tab with their source quotes.</p>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}
