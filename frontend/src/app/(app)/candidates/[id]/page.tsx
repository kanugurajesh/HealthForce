"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import useSWR from "swr";
import { ActivityTab } from "@/components/candidate/activity";
import { CredentialsTab } from "@/components/candidate/credentials";
import { DocumentsTab } from "@/components/candidate/documents";
import { CandidateHeader } from "@/components/candidate/header";
import { OnboardingTab } from "@/components/candidate/onboarding";
import { OverviewTab } from "@/components/candidate/overview";
import { ProfileTab } from "@/components/candidate/profile";
import { ErrorState, LoadingBlock, Tabs } from "@/components/ui";
import { ApiError, fetcher } from "@/lib/api";
import type { CandidateDetail } from "@/lib/types";

type Tab = "overview" | "credentials" | "profile" | "documents" | "onboarding" | "activity";
const TABS: Tab[] = ["overview", "credentials", "profile", "documents", "onboarding", "activity"];

function count(n: number) {
  return n ? <span className="rounded-full bg-slate-100 px-1.5 text-xs text-slate-600">{n}</span> : null;
}

function CandidateView() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "overview") as Tab;

  const { data, error, mutate } = useSWR<CandidateDetail>(`/candidates/${id}`, fetcher, {
    // Poll only while a document is queued or being processed.
    refreshInterval: (d) => (d?.documents.some((doc) => doc.job && (doc.job.status === "pending" || doc.job.status === "processing")) ? 2000 : 0),
  });

  if (error) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <div className="space-y-3">
          <ErrorState error={error} />
          <Link href="/candidates" className="text-sm font-medium text-brand-700 hover:underline">
            ← Back to candidates
          </Link>
        </div>
      );
    }
    return <ErrorState error={error} retry={() => mutate()} />;
  }
  if (!data) return <LoadingBlock rows={8} />;

  const onChanged = (d: CandidateDetail) => mutate(d, { revalidate: false });
  const goTo = (t: string) => router.replace(`${pathname}?tab=${t}`, { scroll: false });
  const unreviewedCreds = data.credentials.filter((c) => c.review_state === "unreviewed").length;
  const unreviewedProfile = [...data.experiences, ...data.qualifications, ...data.skills].filter((c) => c.review_state === "unreviewed").length;
  const openTasks = data.tasks.filter((t) => t.status !== "done" && t.status !== "waived").length;

  return (
    <>
      <Link href="/candidates" className="mb-2 inline-block text-xs font-medium text-slate-500 hover:text-slate-800">
        ← Candidates
      </Link>
      <CandidateHeader c={data} onChanged={onChanged} />
      <Tabs<Tab>
        value={tab}
        onChange={(t) => goTo(t)}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "credentials", label: <>Credentials {count(unreviewedCreds)}</> },
          { id: "profile", label: <>Experience & education {count(unreviewedProfile)}</> },
          { id: "documents", label: <>Documents {count(data.documents.length)}</> },
          { id: "onboarding", label: <>Onboarding {count(openTasks)}</> },
          { id: "activity", label: "Notes & activity" },
        ]}
      />
      <div className="mt-5" role="tabpanel">
        {tab === "overview" && <OverviewTab c={data} onChanged={onChanged} goTo={goTo} />}
        {tab === "credentials" && <CredentialsTab c={data} onChanged={onChanged} />}
        {tab === "profile" && <ProfileTab c={data} onChanged={onChanged} />}
        {tab === "documents" && <DocumentsTab c={data} refresh={() => mutate()} />}
        {tab === "onboarding" && <OnboardingTab c={data} onChanged={onChanged} />}
        {tab === "activity" && <ActivityTab c={data} onChanged={onChanged} />}
      </div>
    </>
  );
}

export default function CandidatePage() {
  return (
    <Suspense fallback={<LoadingBlock rows={8} />}>
      <CandidateView />
    </Suspense>
  );
}
