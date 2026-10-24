"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";
import { ApiErrorMessage, Button, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

const DEMO_USERS = [
  { email: "recruiter@northwind.example", role: "Recruiter", note: "manages candidates, jobs, pipeline" },
  { email: "reviewer@northwind.example", role: "Reviewer", note: "reviews evidence, verifies credentials" },
  { email: "admin@northwind.example", role: "Admin", note: "everything, incl. settings" },
  { email: "viewer@northwind.example", role: "Viewer", note: "read-only" },
  { email: "recruiter@lakeside.example", role: "Other org", note: "separate tenant (isolation demo)" },
];

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState(DEMO_USERS[0].email);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/login", { email, password });
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2">
          <div className="grid size-9 place-items-center rounded-md bg-brand-600 font-bold text-white" aria-hidden>
            HF
          </div>
          <div>
            <h1 className="text-lg font-semibold text-slate-900">HealthForce Intelligence</h1>
            <p className="text-xs text-slate-500">Evidence-based recruitment & credential readiness</p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <Field label="Email" htmlFor="email">
            <Input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </Field>
          <Field label="Password" htmlFor="password">
            <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <ApiErrorMessage error={error} />
          <Button type="submit" variant="primary" className="w-full" loading={busy}>
            Sign in
          </Button>
        </form>
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
          <p className="font-semibold">Demo accounts (synthetic data only)</p>
          <p className="mt-1">
            Password for all: <code className="rounded bg-white px-1">demo-password-2026</code>
          </p>
          <ul className="mt-2 space-y-1">
            {DEMO_USERS.map((u) => (
              <li key={u.email}>
                <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => setEmail(u.email)}>
                  <span className="font-medium">{u.role}</span> — {u.email}
                </button>{" "}
                <span className="text-amber-800/80">({u.note})</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
