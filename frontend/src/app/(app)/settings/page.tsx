"use client";

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import useSWR from "swr";
import { useSession } from "@/components/session";
import { ApiErrorMessage, Badge, Button, Callout, Card, ErrorState, Input, KeyValue, LoadingBlock, PageHeader, Select, useToast } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { TemplateTask } from "@/lib/types";

type Draft = Omit<TemplateTask, "id" | "position"> & { id: string | null; key: number };
let seq = 0;

function TemplateEditor({ initial, onSaved }: { initial: TemplateTask[]; onSaved: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const [tasks, setTasks] = useState<Draft[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const editable = can("manage_settings");
  useEffect(() => setTasks(initial.map((t) => ({ ...t, key: ++seq }))), [initial]);

  const update = (key: number, patch: Partial<Draft>) => setTasks((ts) => ts.map((t) => (t.key === key ? { ...t, ...patch } : t)));
  const move = (i: number, d: number) =>
    setTasks((ts) => {
      const next = [...ts];
      [next[i], next[i + d]] = [next[i + d], next[i]];
      return next;
    });

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.put("/onboarding/template", {
        tasks: tasks.map(({ id, title, description, kind, owner_role, due_offset_days }) => ({ id, title, description, kind, owner_role, due_offset_days })),
      });
      toast("Checklist template saved. It applies to candidates who start onboarding from now on.");
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="py-2 pr-2 font-medium">Task</th>
              <th scope="col" className="px-2 py-2 font-medium">Type</th>
              <th scope="col" className="px-2 py-2 font-medium">Owner role</th>
              <th scope="col" className="px-2 py-2 font-medium">Due (days)</th>
              <th scope="col" className="py-2 pl-2 font-medium"><span className="sr-only">Order</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {tasks.map((t, i) => (
              <tr key={t.key}>
                <td className="py-2 pr-2">
                  <Input aria-label={`Task ${i + 1} title`} value={t.title} onChange={(e) => update(t.key, { title: e.target.value })} disabled={!editable} required minLength={2} />
                </td>
                <td className="px-2 py-2">
                  <Select aria-label={`Task ${i + 1} type`} value={t.kind} onChange={(e) => update(t.key, { kind: e.target.value as Draft["kind"] })} disabled={!editable}>
                    <option value="manual">Manual task</option>
                    <option value="interview">Interview</option>
                    <option value="credential_check">Credential check (rule-gated)</option>
                    <option value="final_review">Final review (reviewer)</option>
                  </Select>
                </td>
                <td className="px-2 py-2">
                  <Select aria-label={`Task ${i + 1} owner`} value={t.owner_role} onChange={(e) => update(t.key, { owner_role: e.target.value as Draft["owner_role"] })} disabled={!editable}>
                    {["recruiter", "reviewer", "admin"].map((r) => (
                      <option key={r} value={r}>
                        {titleCase(r)}
                      </option>
                    ))}
                  </Select>
                </td>
                <td className="w-24 px-2 py-2">
                  <Input aria-label={`Task ${i + 1} due offset`} type="number" min={0} max={180} value={t.due_offset_days} onChange={(e) => update(t.key, { due_offset_days: Number(e.target.value) })} disabled={!editable} />
                </td>
                <td className="whitespace-nowrap py-2 pl-2">
                  {editable && (
                    <>
                      <Button type="button" size="sm" variant="ghost" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move up">
                        <ArrowUp className="size-3.5" />
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => move(i, 1)} disabled={i === tasks.length - 1} aria-label="Move down">
                        <ArrowDown className="size-3.5" />
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setTasks((ts) => ts.filter((x) => x.key !== t.key))} aria-label={`Remove ${t.title}`}>
                        <Trash2 className="size-3.5" />
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ApiErrorMessage error={error} />
      {editable && (
        <div className="flex justify-between">
          <Button type="button" onClick={() => setTasks((ts) => [...ts, { id: null, key: ++seq, title: "", description: null, kind: "manual", owner_role: "recruiter", due_offset_days: 7 }])}>
            <Plus className="size-4" aria-hidden /> Add task
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            Save template
          </Button>
        </div>
      )}
    </form>
  );
}

export default function SettingsPage() {
  const { meta, user, can } = useSession();
  const template = useSWR<TemplateTask[]>("/onboarding/template", fetcher);
  return (
    <>
      <PageHeader title="Settings" description={`Organization: ${user.organization.name}`} />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Onboarding checklist template" description="Created for each candidate who enters onboarding. Existing checklists are not changed. Exactly one final review is required." className="xl:col-span-2">
          {!can("manage_settings") && (
            <div className="mb-3">
              <Callout tone="info">Only administrators can change the template.</Callout>
            </div>
          )}
          {template.error ? <ErrorState error={template.error} retry={() => template.mutate()} /> : !template.data ? <LoadingBlock /> : <TemplateEditor initial={template.data} onSaved={() => template.mutate()} />}
        </Card>
        <div className="space-y-4">
          <Card title="System configuration" description="Read-only; set via server environment variables.">
            <KeyValue
              items={[
                ["Extraction", <span key="p">{meta.extraction_provider.label}</span>],
                ["Verification", meta.verification_mode === "simulated" ? <Badge key="v" tone="warning">Simulated (demo)</Badge> : <Badge key="v" tone="neutral">Manual only</Badge>],
                ["Expiring-soon window", `${meta.expiring_soon_days} days`],
                ["Max upload size", `${meta.max_upload_mb} MB`],
                ["Rules as-of date", meta.as_of],
              ]}
            />
          </Card>
          <Card title="Credential catalog" description="Where each credential would be verified. None of these sources is integrated.">
            <ul className="space-y-2 text-sm">
              {meta.credential_types.map((t) => (
                <li key={t.code}>
                  <p className="font-medium text-slate-800">{t.label}</p>
                  <p className="text-xs text-slate-500">{t.verification_source}</p>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
