"use client";

import { Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { useSession } from "@/components/session";
import { ApiErrorMessage, Button, Card, Field, Input, Select, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { JobRole, Requirement } from "@/lib/types";

type Draft = Omit<Requirement, "id" | "position" | "label"> & { label: string; key: number; labelTouched: boolean };

let keySeq = 0;
const blank = (kind: Draft["kind"]): Draft => ({
  key: ++keySeq,
  labelTouched: false,
  kind,
  codes: [],
  label: "",
  is_required: kind !== "skill",
  weight: kind === "skill" ? 1 : 3,
  min_years: kind === "experience" ? 1 : null,
  setting: kind === "experience" ? "acute_care" : null,
  min_valid_days: null,
});

export function JobForm({ job }: { job?: JobRole }) {
  const { meta } = useSession();
  const router = useRouter();
  const toast = useToast();
  const [title, setTitle] = useState(job?.title ?? "");
  const [department, setDepartment] = useState(job?.department ?? "");
  const [location, setLocation] = useState(job?.location ?? "");
  const [description, setDescription] = useState(job?.description ?? "");
  const [status, setStatus] = useState(job?.status ?? "open");
  const [reqs, setReqs] = useState<Draft[]>(job ? job.requirements.map((r) => ({ ...r, key: ++keySeq, labelTouched: false })) : [blank("credential")]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // A label the user never edited is regenerated server-side whenever the requirement itself changes.
  const update = (key: number, patch: Partial<Draft>) =>
    setReqs((rs) =>
      rs.map((r) => {
        if (r.key !== key) return r;
        if ("label" in patch) return { ...r, ...patch, labelTouched: true };
        const structural = ["codes", "min_years", "setting", "min_valid_days"].some((k) => k in patch);
        return { ...r, ...patch, label: structural && !r.labelTouched ? "" : r.label };
      }),
    );
  const catalog = (kind: Draft["kind"]) => (kind === "credential" ? meta.credential_types : kind === "qualification" ? meta.qualifications : meta.skills);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      title: title.trim(),
      department: department.trim() || null,
      location: location.trim() || null,
      description: description.trim() || null,
      status,
      requirements: reqs.map((r) => ({
        kind: r.kind,
        codes: r.kind === "experience" ? [] : r.codes,
        // An unchanged auto-generated label is regenerated server-side from the codes.
        label: r.label.trim() || null,
        is_required: r.is_required,
        weight: r.weight,
        min_years: r.kind === "experience" ? r.min_years : null,
        setting: r.kind === "experience" ? r.setting : null,
        min_valid_days: r.kind === "credential" ? r.min_valid_days : null,
      })),
    };
    try {
      const saved = job ? await api.put<JobRole>(`/job-roles/${job.id}`, body) : await api.post<JobRole>("/job-roles", body);
      toast(job ? "Job role updated." : "Job role created.");
      router.push(`/jobs/${saved.id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Card title="Role details">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Title" htmlFor="j-title" required>
            <Input id="j-title" value={title} onChange={(e) => setTitle(e.target.value)} required minLength={2} maxLength={200} />
          </Field>
          <Field label="Status" htmlFor="j-status">
            <Select id="j-status" value={status} onChange={(e) => setStatus(e.target.value as "open" | "closed")}>
              <option value="open">Open</option>
              <option value="closed">Closed</option>
            </Select>
          </Field>
          <Field label="Department" htmlFor="j-dept">
            <Input id="j-dept" value={department} onChange={(e) => setDepartment(e.target.value)} />
          </Field>
          <Field label="Location" htmlFor="j-loc">
            <Input id="j-loc" value={location} onChange={(e) => setLocation(e.target.value)} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Description" htmlFor="j-desc">
              <Textarea id="j-desc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={4000} />
            </Field>
          </div>
        </div>
      </Card>

      <Card
        title="Requirements"
        description="Required requirements decide eligibility. Weights (1–5) only affect the ranking score. A candidate is never rejected automatically."
        actions={
          <div className="flex flex-wrap gap-1.5">
            {(["credential", "qualification", "experience", "skill"] as const).map((k) => (
              <Button key={k} size="sm" type="button" onClick={() => setReqs((rs) => [...rs, blank(k)])}>
                <Plus className="size-3.5" aria-hidden /> {titleCase(k)}
              </Button>
            ))}
          </div>
        }
        bodyClassName="p-0"
      >
        {reqs.length === 0 && <p className="p-4 text-sm text-slate-500">No requirements yet. Add at least one so candidates can be evaluated.</p>}
        <ul className="divide-y divide-slate-100">
          {reqs.map((r, idx) => (
            <li key={r.key} className="grid gap-3 p-4 lg:grid-cols-[8rem_1fr_auto]">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {idx + 1}. {r.kind}
                </p>
                <label className="mt-2 flex items-center gap-1.5 text-sm">
                  <input type="checkbox" checked={r.is_required} onChange={(e) => update(r.key, { is_required: e.target.checked })} />
                  Required
                </label>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {r.kind === "experience" ? (
                  <>
                    <Field label="Minimum years" htmlFor={`r-y-${r.key}`}>
                      <Input id={`r-y-${r.key}`} type="number" step="0.5" min={0} max={40} value={r.min_years ?? ""} onChange={(e) => update(r.key, { min_years: e.target.value === "" ? null : Number(e.target.value) })} required />
                    </Field>
                    <Field label="Care setting" htmlFor={`r-s-${r.key}`}>
                      <Select id={`r-s-${r.key}`} value={r.setting ?? "any"} onChange={(e) => update(r.key, { setting: e.target.value })}>
                        {meta.experience_requirement_settings.map((s) => (
                          <option key={s} value={s}>
                            {titleCase(s)}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  </>
                ) : (
                  <fieldset className="space-y-1">
                    <legend className="text-xs font-medium text-slate-700">Accepted {r.kind}s — any one satisfies the requirement</legend>
                    <div className="max-h-32 space-y-1 overflow-y-auto rounded-md border border-slate-300 bg-white p-2">
                      {catalog(r.kind).map((c) => (
                        <label key={c.code} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={r.codes.includes(c.code)}
                            onChange={(e) => update(r.key, { codes: e.target.checked ? [...r.codes, c.code] : r.codes.filter((x) => x !== c.code) })}
                          />
                          {c.label}
                        </label>
                      ))}
                    </div>
                    {r.codes.length === 0 && <p className="text-xs text-amber-700">Select at least one.</p>}
                  </fieldset>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Weight" htmlFor={`r-w-${r.key}`}>
                    <Select id={`r-w-${r.key}`} value={r.weight} onChange={(e) => update(r.key, { weight: Number(e.target.value) })}>
                      {[1, 2, 3, 4, 5].map((w) => (
                        <option key={w} value={w}>
                          {w}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {r.kind === "credential" && (
                    <Field label="Min. days valid" htmlFor={`r-v-${r.key}`}>
                      <Input id={`r-v-${r.key}`} type="number" min={0} max={730} value={r.min_valid_days ?? ""} onChange={(e) => update(r.key, { min_valid_days: e.target.value === "" ? null : Number(e.target.value) })} />
                    </Field>
                  )}
                </div>
                <div className="sm:col-span-2">
                  <Field label="Label (optional — generated from the selection if empty)" htmlFor={`r-l-${r.key}`}>
                    <Input id={`r-l-${r.key}`} value={r.label} onChange={(e) => update(r.key, { label: e.target.value })} maxLength={200} />
                  </Field>
                </div>
              </div>
              <div>
                <Button type="button" variant="ghost" size="sm" onClick={() => setReqs((rs) => rs.filter((x) => x.key !== r.key))} aria-label={`Remove requirement ${idx + 1}`}>
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <ApiErrorMessage error={error} />
      <div className="flex justify-end gap-2">
        <Button type="button" onClick={() => router.back()}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={busy}>
          {job ? "Save changes" : "Create job role"}
        </Button>
      </div>
    </form>
  );
}
