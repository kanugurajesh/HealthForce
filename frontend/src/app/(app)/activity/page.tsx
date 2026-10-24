"use client";

import { useState } from "react";
import useSWR from "swr";
import { AuditList } from "@/components/audit";
import { Card, ErrorState, LoadingBlock, PageHeader, Select } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { AuditEvent } from "@/lib/types";

const ENTITY_TYPES = [
  ["", "All activity"],
  ["candidate", "Candidates"],
  ["credential", "Credentials"],
  ["document", "Documents & processing"],
  ["onboarding_task", "Onboarding tasks"],
  ["job_role", "Job roles"],
  ["note", "Notes & decisions"],
  ["experience", "Experience edits"],
  ["onboarding_template", "Settings"],
];

export default function ActivityPage() {
  const [entity, setEntity] = useState("");
  const { data, error, mutate } = useSWR<AuditEvent[]>(`/audit?limit=200${entity ? `&entity_type=${entity}` : ""}`, fetcher);
  return (
    <>
      <PageHeader
        title="Activity log"
        description="Append-only record of every important change: actor, action, time and reason. Entries cannot be edited or deleted through the application."
        actions={
          <Select aria-label="Filter activity" value={entity} onChange={(e) => setEntity(e.target.value)} className="w-56">
            {ENTITY_TYPES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        }
      />
      <Card>{error ? <ErrorState error={error} retry={() => mutate()} /> : !data ? <LoadingBlock rows={8} /> : <AuditList events={data} />}</Card>
    </>
  );
}
