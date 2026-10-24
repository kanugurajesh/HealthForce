"use client";

import { type FormEvent, useState } from "react";
import useSWR from "swr";
import { AuditList } from "@/components/audit";
import { useSession } from "@/components/session";
import { ApiErrorMessage, Badge, Button, Card, ErrorState, Field, LoadingBlock, Select, Textarea, useToast } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { AuditEvent, CandidateDetail } from "@/lib/types";

const DECISION_TONE = { advance: "success", hold: "warning", decline: "danger" } as const;

export function ActivityTab({ c, onChanged }: { c: CandidateDetail; onChanged: (d: CandidateDetail) => void }) {
  const { can } = useSession();
  const toast = useToast();
  const activity = useSWR<AuditEvent[]>(`/candidates/${c.id}/activity`, fetcher);
  const [kind, setKind] = useState("note");
  const [decision, setDecision] = useState("advance");
  const [body, setBody] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.post<CandidateDetail>(`/candidates/${c.id}/notes`, { kind, decision: kind === "decision" ? decision : null, body }));
      setBody("");
      toast(kind === "decision" ? "Decision recorded." : "Note added.");
      activity.mutate();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Notes & review decisions" description="Decisions are recorded for people; they do not change the candidate's stage automatically.">
        {can("add_notes") && (
          <form onSubmit={submit} className="mb-4 space-y-2">
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="Type" htmlFor="n-kind">
                <Select id="n-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="note">Note</option>
                  <option value="decision">Review decision</option>
                </Select>
              </Field>
              {kind === "decision" && (
                <Field label="Decision" htmlFor="n-dec">
                  <Select id="n-dec" value={decision} onChange={(e) => setDecision(e.target.value)}>
                    <option value="advance">Advance</option>
                    <option value="hold">Hold</option>
                    <option value="decline">Decline</option>
                  </Select>
                </Field>
              )}
            </div>
            <Field label={kind === "decision" ? "Rationale" : "Note"} htmlFor="n-body" required>
              <Textarea id="n-body" value={body} onChange={(e) => setBody(e.target.value)} required maxLength={4000} />
            </Field>
            <ApiErrorMessage error={error} />
            <Button type="submit" variant="primary" size="sm" loading={busy}>
              {kind === "decision" ? "Record decision" : "Add note"}
            </Button>
          </form>
        )}
        {c.notes.length === 0 ? (
          <p className="text-sm text-slate-500">No notes yet.</p>
        ) : (
          <ul className="space-y-3">
            {c.notes.map((n) => (
              <li key={n.id} className="rounded-md border border-slate-200 p-3">
                <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  {n.decision && <Badge tone={DECISION_TONE[n.decision]}>Decision: {n.decision}</Badge>}
                  <span>
                    {n.author_name ?? "Unknown"} · {formatDateTime(n.created_at)}
                  </span>
                </div>
                <p className="whitespace-pre-line text-sm text-slate-800">{n.body}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Activity history" description="Append-only audit trail: who did what, when, and why.">
        {activity.error ? <ErrorState error={activity.error} retry={() => activity.mutate()} /> : !activity.data ? <LoadingBlock rows={5} /> : <AuditList events={activity.data} showCandidate={false} />}
      </Card>
    </div>
  );
}
