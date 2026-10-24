"use client";

import { AppShell } from "@/components/app-shell";
import { SessionProvider } from "@/components/session";
import { ErrorState, Skeleton, ToastProvider } from "@/components/ui";

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <SessionProvider
        loading={
          <div className="flex min-h-screen items-center justify-center" role="status" aria-label="Loading">
            <Skeleton className="h-8 w-48" />
          </div>
        }
        error={(e, retry) => (
          <div className="mx-auto max-w-lg p-8">
            <ErrorState error={e} retry={retry} />
          </div>
        )}
      >
        {() => <AppShell>{children}</AppShell>}
      </SessionProvider>
    </ToastProvider>
  );
}
