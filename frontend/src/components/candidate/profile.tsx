"use client";

import { ClaimActions, EvidenceQuote, Flags, ReviewMeta, SourceBadge } from "@/components/claims";
import { Badge, Card, EmptyState } from "@/components/ui";
import { formatDate, titleCase } from "@/lib/format";
import type { CandidateDetail } from "@/lib/types";

type Props = { c: CandidateDetail; onChanged: (d: CandidateDetail) => void };

export function ProfileTab({ c, onChanged }: Props) {
  const skills = [...c.skills].sort((a, b) => Number(a.review_state === "rejected") - Number(b.review_state === "rejected"));
  return (
    <div className="space-y-4">
      <Card title="Work experience" description="Durations count toward experience requirements only once reviewed. Care settings are classified deterministically from the text." bodyClassName="p-0">
        {c.experiences.length === 0 ? (
          <div className="p-4">
            <EmptyState title="No work history extracted">Upload a resume, or correct extracted data if a role was missed.</EmptyState>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {c.experiences.map((e) => (
              <li key={e.id} className={`space-y-2 p-4 ${e.review_state === "rejected" ? "opacity-60" : ""}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{e.title}</p>
                    <p className="text-sm text-slate-600">
                      {e.employer ?? "Employer not stated"} · {e.start_date ? formatDate(e.start_date) : <span className="text-amber-700">start unknown</span>} –{" "}
                      {e.is_current ? "present" : e.end_date ? formatDate(e.end_date) : <span className="text-amber-700">end unknown</span>}
                      {e.duration_years !== null && <span className="text-slate-500"> ({e.duration_years} yrs)</span>}
                    </p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {e.settings.length ? e.settings.map((s) => <Badge key={s} tone="neutral" icon={false}>{titleCase(s)}</Badge>) : <Badge tone="warning">Setting unclassified</Badge>}
                      <SourceBadge source={e.source} />
                    </div>
                  </div>
                  <ClaimActions kind="experiences" claim={e} onChanged={onChanged} />
                </div>
                {e.description && <p className="text-sm text-slate-700">{e.description}</p>}
                <EvidenceQuote claim={e} />
                <Flags flags={e.flags} />
                <ReviewMeta claim={e} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Education & qualifications" bodyClassName="p-0">
        {c.qualifications.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">No qualifications extracted.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {c.qualifications.map((q) => (
              <li key={q.id} className={`space-y-2 p-4 ${q.review_state === "rejected" ? "opacity-60" : ""}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{q.code === "OTHER" ? q.name : q.label}</p>
                    <p className="text-sm text-slate-600">
                      {q.institution ?? "Institution not stated"}
                      {q.completion_year ? ` · ${q.completion_year}` : ""}
                    </p>
                  </div>
                  <ClaimActions kind="qualifications" claim={q} onChanged={onChanged} />
                </div>
                <EvidenceQuote claim={q} />
                <Flags flags={q.flags} />
                <ReviewMeta claim={q} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Skills" description="Matched to the skills catalog; free-text skills are shown but do not count toward requirements." bodyClassName="p-0">
        {skills.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">No skills extracted.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {skills.map((s) => (
              <li key={s.id} className={`grid gap-2 p-4 md:grid-cols-[14rem_1fr_auto] md:items-start ${s.review_state === "rejected" ? "opacity-60" : ""}`}>
                <div>
                  <p className="text-sm font-medium text-slate-900">{s.label}</p>
                  {s.code === "other" && <p className="text-xs text-slate-500">Not in catalog</p>}
                  <div className="mt-1">
                    <ReviewMeta claim={s} />
                  </div>
                </div>
                <div className="space-y-1">
                  <EvidenceQuote claim={s} />
                  <Flags flags={s.flags} />
                </div>
                <ClaimActions kind="skills" claim={s} onChanged={onChanged} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
