"use client";

import { RotateCw } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import useSWR from "swr";
import { useSession } from "@/components/session";
import { JobStateBadge } from "@/components/status";
import { Button, Callout, EmptyState, ErrorState, LoadingBlock, PageHeader, Select, useToast } from "@/components/ui";
import { api, fetcher } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ProcessingJobRow } from "@/lib/types";

function RetryButton({ row, onDone }: { row: ProcessingJobRow; onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant={row.status === "failed" ? "primary" : "ghost"}
      loading={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await api.post(`/documents/${row.document_id}/process`);
          toast(row.status === "failed" ? "Retry queued." : "Re-extraction queued.");
          onDone();
        } catch (e) {
          toast(e instanceof Error ? e.message : "Could not queue.", "danger");
        } finally {
          setBusy(false);
        }
      }}
    >
      <RotateCw className="size-3.5" aria-hidden /> {row.status === "failed" ? "Retry" : "Re-run"}
    </Button>
  );
}

function ProcessingView() {
  const { can, meta } = useSession();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const status = params.get("status") ?? "";
  const { data, error, mutate } = useSWR<ProcessingJobRow[]>(`/processing-jobs${status ? `?status=${status}` : ""}`, fetcher, {
    refreshInterval: (d) => (d?.some((j) => j.status === "pending" || j.status === "processing") ? 2000 : 0),
  });

  return (
    <>
      <PageHeader
        title="Document processing"
        description="Each upload becomes a background job: queued → processing → succeeded or failed. Transient failures retry automatically with backoff; permanent ones need a person."
        actions={
          <Select aria-label="Filter by job status" value={status} onChange={(e) => router.replace(e.target.value ? `${pathname}?status=${e.target.value}` : pathname)} className="w-44">
            <option value="">All jobs</option>
            <option value="failed">Failed</option>
            <option value="pending">Queued</option>
            <option value="processing">Processing</option>
            <option value="succeeded">Succeeded</option>
          </Select>
        }
      />
      <div className="mb-4">
        <Callout tone={meta.extraction_provider.is_mock ? "warning" : "info"} title={`Extraction provider: ${meta.extraction_provider.label}`}>
          {meta.extraction_provider.is_mock
            ? "Set HF_EXTRACTION_PROVIDER=groq and GROQ_API_KEY on the server to use gpt-oss-120b. Every result is still validated and grounded against the document text."
            : "Model output is validated against a strict schema and every value is checked against the document text before it is stored."}
        </Callout>
      </div>
      {error ? (
        <ErrorState error={error} retry={() => mutate()} />
      ) : !data ? (
        <LoadingBlock rows={6} />
      ) : data.length === 0 ? (
        <EmptyState title={status ? "No jobs with this status" : "No documents have been uploaded yet"} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">Document</th>
                <th scope="col" className="px-4 py-2 font-medium">Candidate</th>
                <th scope="col" className="px-4 py-2 font-medium">Status</th>
                <th scope="col" className="px-4 py-2 font-medium">Attempts</th>
                <th scope="col" className="px-4 py-2 font-medium">Result</th>
                <th scope="col" className="px-4 py-2 font-medium">Updated</th>
                <th scope="col" className="px-4 py-2 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((j) => {
                const claims = (j.stats?.claims ?? {}) as Record<string, number>;
                const total = Object.values(claims).reduce((a, b) => a + b, 0);
                return (
                  <tr key={j.id} className="align-top">
                    <td className="px-4 py-3">
                      <Link href={`/documents/${j.document_id}`} className="font-medium text-slate-900 hover:underline">
                        {j.document_filename}
                      </Link>
                      <p className="text-xs text-slate-500">{j.document_kind} · {j.provider}</p>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/candidates/${j.candidate_id}`} className="text-slate-700 hover:underline">
                        {j.candidate_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <JobStateBadge value={j.status} />
                    </td>
                    <td className="px-4 py-3 tabular-nums text-slate-700">
                      {j.attempts}/{j.max_attempts}
                    </td>
                    <td className="max-w-sm px-4 py-3 text-xs">
                      {j.status === "failed" || (j.status === "pending" && j.last_error) ? (
                        <span className="text-red-700">
                          <code className="mr-1">{j.error_code}</code>
                          {j.last_error}
                          {j.status === "pending" && j.next_attempt_at && <span className="block text-slate-500">Next attempt {formatDateTime(j.next_attempt_at)}</span>}
                        </span>
                      ) : j.status === "succeeded" ? (
                        <span className="text-slate-600">
                          {total} item(s) extracted
                          {typeof j.stats?.dropped === "number" && j.stats.dropped > 0 ? `, ${j.stats.dropped} unsupported discarded` : ""}
                          {j.warnings.length > 0 ? ` · ${j.warnings.length} note(s)` : ""}
                          {typeof j.stats?.duration_ms === "number" ? ` · ${j.stats.duration_ms} ms` : ""}
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">{formatDateTime(j.finished_at ?? j.started_at ?? j.created_at)}</td>
                    <td className="px-4 py-3">{can("upload_documents") && (j.status === "failed" || j.status === "succeeded") && <RetryButton row={j} onDone={() => mutate()} />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function ProcessingPage() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} />}>
      <ProcessingView />
    </Suspense>
  );
}
