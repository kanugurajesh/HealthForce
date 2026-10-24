"use client";

import { JobForm } from "@/components/job-form";
import { useSession } from "@/components/session";
import { Callout, PageHeader } from "@/components/ui";

export default function NewJobPage() {
  const { can } = useSession();
  return (
    <>
      <PageHeader title="New job role" back={{ href: "/jobs", label: "Job roles" }} />
      {can("manage_jobs") ? <JobForm /> : <Callout tone="warning">Your role cannot create job roles.</Callout>}
    </>
  );
}
