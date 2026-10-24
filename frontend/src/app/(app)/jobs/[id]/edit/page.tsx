"use client";

import { useParams } from "next/navigation";
import useSWR from "swr";
import { JobForm } from "@/components/job-form";
import { useSession } from "@/components/session";
import { Callout, ErrorState, LoadingBlock, PageHeader } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { JobRole } from "@/lib/types";

export default function EditJobPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useSession();
  const { data, error } = useSWR<JobRole>(`/job-roles/${id}`, fetcher, { revalidateOnFocus: false });
  if (error) return <ErrorState error={error} />;
  if (!data) return <LoadingBlock />;
  return (
    <>
      <PageHeader title={`Edit “${data.title}”`} back={{ href: `/jobs/${id}`, label: data.title }} />
      {can("manage_jobs") ? <JobForm job={data} /> : <Callout tone="warning">Your role cannot edit job roles.</Callout>}
    </>
  );
}
