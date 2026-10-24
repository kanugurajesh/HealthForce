"use client";

import clsx from "clsx";
import { Activity, BriefcaseMedical, Cog, FileClock, LayoutDashboard, LogOut, Menu, ShieldAlert, Users, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";
import { api } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { useSession } from "./session";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/candidates", label: "Candidates", icon: Users },
  { href: "/jobs", label: "Job roles", icon: BriefcaseMedical },
  { href: "/processing", label: "Document processing", icon: FileClock },
  { href: "/activity", label: "Activity log", icon: Activity },
  { href: "/settings", label: "Settings", icon: Cog },
];

function DemoBanner() {
  const { meta } = useSession();
  const notes: string[] = [];
  if (meta.extraction_provider.is_mock) notes.push("documents are processed by a deterministic mock extractor, not AI");
  else if (meta.extraction_provider.misconfigured) notes.push("AI extraction is enabled but GROQ_API_KEY is not set — uploads will fail until it is configured");
  else notes.push(`document text (contact details redacted) is sent to ${meta.extraction_provider.label} for extraction`);
  if (meta.verification_mode === "simulated") notes.push("“simulated” verifications do not contact any registry");
  return (
    <div className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900 sm:px-6">
      <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <p>
        <strong>Demo environment with synthetic data.</strong> {notes.length ? `Note: ${notes.join("; ")}.` : ""} No external credential registries are
        integrated. Not for real candidate or patient information.
      </p>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  async function logout() {
    await api.post("/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  const nav = (
    <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 px-3 py-4">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={() => setOpen(false)}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium",
              active ? "bg-brand-50 text-brand-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );

  const brand = (
    <div className="flex items-center gap-2 px-5 py-4">
      <div className="grid size-8 place-items-center rounded-md bg-brand-600 text-sm font-bold text-white" aria-hidden>
        HF
      </div>
      <div className="leading-tight">
        <p className="text-sm font-semibold text-slate-900">HealthForce</p>
        <p className="text-[11px] text-slate-500">Intelligence</p>
      </div>
    </div>
  );

  const userBox = (
    <div className="border-t border-slate-200 p-3">
      <div className="rounded-md bg-slate-50 px-3 py-2">
        <p className="truncate text-sm font-medium text-slate-900">{user.full_name}</p>
        <p className="truncate text-xs text-slate-500">
          {titleCase(user.role)} · {user.organization.name}
        </p>
      </div>
      <button onClick={logout} className="mt-2 flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
        <LogOut className="size-4" aria-hidden /> Sign out
      </button>
    </div>
  );

  return (
    <div className="min-h-screen lg:pl-60">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-slate-200 bg-white lg:flex">
        {brand}
        {nav}
        {userBox}
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} aria-hidden />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-white shadow-xl">
            <div className="flex items-center justify-between pr-3">
              {brand}
              <button onClick={() => setOpen(false)} aria-label="Close navigation" className="rounded p-1.5 hover:bg-slate-100">
                <X className="size-4" />
              </button>
            </div>
            {nav}
            {userBox}
          </aside>
        </div>
      )}
      <div className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-2 lg:hidden">
        <button onClick={() => setOpen(true)} aria-label="Open navigation" className="rounded p-1.5 hover:bg-slate-100">
          <Menu className="size-5" />
        </button>
        <span className="text-sm font-semibold">HealthForce Intelligence</span>
      </div>
      <DemoBanner />
      <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {children}
      </main>
    </div>
  );
}
