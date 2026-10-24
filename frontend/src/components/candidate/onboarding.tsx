"use client";

import { Lock } from "lucide-react";
import { useState } from "react";
import { ReasonDialog } from "@/components/claims";
import { useSession } from "@/components/session";
import { ApiErrorMessage, Badge, Callout, Card, EmptyState, Input, Select, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, formatDateTime, titleCase } from "@/lib/format";
import type { CandidateDetail, Task } from "@/lib/types";

const STATUS_LABEL: Record<Task["status"], string> = { todo: "To do", in_progress: "In progress", done: "Done", waived: "Waived" };
const KIND_LABEL: Record<Task["kind"], string> = { manual: "Task", interview: "Interview", credential_check: "Credential check (rule-gated)", final_review: "Final review (reviewer only)" };

function TaskRow({ t, onChanged }: { t: Task; onChanged: (d: CandidateDetail) => void }) {
  const { can, meta } = useSession();
  const toast = useToast();
  const [error, setError] = useState<unknown>(null);
  const [waiving, setWaiving] = useState(false);
  const [notes, setNotes] = useState(t.notes ?? "");
  const editable = can("manage_onboarding");
  const closed = t.status === "done" || t.status === "waived";

  async function patch(body: Record<string, unknown>, message: string) {
    setError(null);
    try {
      onChanged(await api.patch<CandidateDetail>(`/tasks/${t.id}`, body));
      toast(message);
    } catch (e) {
      setError(e);
    }
  }

  return (
    <li className="space-y-2 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className={`text-sm font-semibold ${closed ? "text-slate-500 line-through decoration-slate-300" : "text-slate-900"}`}>{t.title}</p>
            <Badge tone={t.status === "done" ? "success" : t.status === "waived" ? "muted" : t.blockers.length ? "warning" : "neutral"}>{STATUS_LABEL[t.status]}</Badge>
            {t.overdue && <Badge tone="danger">Overdue</Badge>}
            <Badge tone="muted" icon={false}>{KIND_LABEL[t.kind]}</Badge>
          </div>
          {t.description && <p className="mt-0.5 text-xs text-slate-500">{t.description}</p>}
          <p className="mt-1 text-xs text-slate-500">
            Owner role: {titleCase(t.owner_role)} · Due {formatDate(t.due_date)}
            {t.completed_at && ` · ${t.status === "waived" ? "Waived" : "Completed"} by ${t.completed_by_name ?? "—"} on ${formatDateTime(t.completed_at)}`}
          </p>
          {t.waived_reason && <p className="mt-0.5 text-xs italic text-slate-600">Waiver reason: {t.waived_reason}</p>}
        </div>
        {editable && (
          <div className="grid w-full gap-2 sm:w-auto sm:grid-cols-[9rem_10rem_9rem]">
            <Select
              aria-label={`Status of ${t.title}`}
              value={t.status}
              onChange={(e) => {
                const v = e.target.value as Task["status"];
                if (v === "waived") setWaiving(true);
                else patch({ status: v }, `“${t.title}” marked ${STATUS_LABEL[v].toLowerCase()}.`);
              }}
            >
              {(Object.keys(STATUS_LABEL) as Task["status"][]).map((s) => (
                <option key={s} value={s} disabled={(s === "done" && t.blockers.length > 0) || (s === "waived" && t.kind === "final_review")}>
                  {STATUS_LABEL[s]}
                  {s === "done" && t.blockers.length > 0 ? " (blocked)" : ""}
                </option>
              ))}
            </Select>
            <Select aria-label={`Owner of ${t.title}`} value={t.owner?.id ?? ""} onChange={(e) => patch({ owner_id: e.target.value || null }, "Owner updated.")}>
              <option value="">Unassigned</option>
              {meta.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} ({u.role})
                </option>
              ))}
            </Select>
            <Input aria-label={`Due date of ${t.title}`} type="date" value={t.due_date ?? ""} onChange={(e) => patch({ due_date: e.target.value || null }, "Due date updated.")} />
          </div>
        )}
      </div>
      {t.blockers.length > 0 && (
        <div className="flex gap-2 rounded-md bg-amber-50 p-2.5 text-xs text-amber-900 ring-1 ring-inset ring-amber-200">
          <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <div>
            <p className="font-medium">Blocked — cannot be completed yet</p>
            <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
              {t.blockers.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {editable && !closed && (
        <div className="flex gap-2">
          <Textarea aria-label={`Notes for ${t.title}`} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes (e.g. interview booked for Nov 4 with unit manager)" className="min-h-9 text-xs" />
          {notes !== (t.notes ?? "") && (
            <button className="self-start rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium hover:bg-slate-50" onClick={() => patch({ notes }, "Notes saved.")}>
              Save
            </button>
          )}
        </div>
      )}
      {t.notes && closed && <p className="text-xs text-slate-600">Notes: {t.notes}</p>}
      <ApiErrorMessage error={error} />
      <ReasonDialog
        open={waiving}
        title={`Waive “${t.title}”`}
        description="Waiving records that this task is intentionally not required for this candidate. A reason is mandatory and audited."
        confirmLabel="Waive task"
        onClose={() => setWaiving(false)}
        onSubmit={async (reason) => {
          onChanged(await api.patch<CandidateDetail>(`/tasks/${t.id}`, { status: "waived", waived_reason: reason }));
          toast("Task waived.");
        }}
      />
    </li>
  );
}

export function OnboardingTab({ c, onChanged }: { c: CandidateDetail; onChanged: (d: CandidateDetail) => void }) {
  if (c.tasks.length === 0) {
    return (
      <EmptyState title="Onboarding has not started">
        The organization&apos;s checklist is created when the candidate is moved to the <strong>Onboarding</strong> stage.
      </EmptyState>
    );
  }
  const done = c.tasks.filter((t) => t.status === "done" || t.status === "waived").length;
  const pct = Math.round((done / c.tasks.length) * 100);
  return (
    <div className="space-y-4">
      <Card title="Onboarding progress">
        <div className="flex items-center gap-3">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Onboarding progress">
            <div className="h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-sm tabular-nums text-slate-700">
            {done}/{c.tasks.length} complete
          </span>
        </div>
        {c.status === "cleared" ? (
          <div className="mt-3">
            <Callout tone="success">Cleared to start.</Callout>
          </div>
        ) : (
          c.clearance_blockers.length > 0 && (
            <div className="mt-3">
              <Callout tone="warning" title="Before this candidate can be cleared to start">
                <ul className="list-disc space-y-0.5 pl-4">
                  {c.clearance_blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </Callout>
            </div>
          )
        )}
        <p className="mt-3 text-xs text-slate-500">Tasks are never completed automatically. Rule-gated tasks unlock only when the underlying evidence is reviewed and verified.</p>
      </Card>
      <Card title="Checklist" bodyClassName="p-0">
        <ul className="divide-y divide-slate-100">
          {c.tasks.map((t) => (
            <TaskRow key={t.id} t={t} onChanged={onChanged} />
          ))}
        </ul>
      </Card>
    </div>
  );
}
