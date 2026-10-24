/** Renders real pages against fixtures captured from the live API (scripts/capture-fixtures.py). */
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { vi } from "vitest";
import { SessionProvider } from "@/components/session";
import { ToastProvider } from "@/components/ui";
import candidateJordan from "./fixtures/candidate-jordan.json";
import candidateMaya from "./fixtures/candidate-maya.json";
import candidateTom from "./fixtures/candidate-tom.json";
import candidates from "./fixtures/candidates.json";
import dashboard from "./fixtures/dashboard.json";
import documentInjection from "./fixtures/document-injection.json";
import documentLicense from "./fixtures/document-license.json";
import jobMatches from "./fixtures/job-matches.json";
import me from "./fixtures/me.json";
import meta from "./fixtures/meta.json";

export const fx = { me, meta, dashboard, candidates, candidateMaya, candidateTom, candidateJordan, documentInjection, documentLicense, jobMatches };

export type Call = { method: string; path: string; body: unknown };

/** Install a fetch mock that serves fixtures for GETs and records mutations. */
export function mockApi(overrides: Record<string, unknown> = {}) {
  const calls: Call[] = [];
  const routes: Record<string, unknown> = {
    "/auth/me": me,
    "/meta": meta,
    "/dashboard": dashboard,
    "/candidates": candidates,
    [`/candidates/${candidateMaya.id}`]: candidateMaya,
    [`/candidates/${candidateTom.id}`]: candidateTom,
    [`/candidates/${candidateJordan.id}`]: candidateJordan,
    [`/candidates/${candidateMaya.id}/activity`]: [],
    [`/candidates/${candidateTom.id}/activity`]: [],
    [`/documents/${documentInjection.id}`]: documentInjection,
    [`/documents/${documentLicense.id}`]: documentLicense,
    [`/job-roles/${jobMatches.job.id}/matches?scope=all`]: jobMatches,
    "/job-roles": [jobMatches.job],
    ...overrides,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace(/^\/api/, "");
    const method = init?.method ?? "GET";
    if (method !== "GET") {
      calls.push({ method, path: url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return new Response(JSON.stringify(candidateJordan), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    const key = Object.keys(routes).find((k) => k === url) ?? Object.keys(routes).find((k) => url.split("?")[0] === k);
    if (!key) return new Response(JSON.stringify({ error: { code: "not_found", message: `No fixture for ${url}` } }), { status: 404 });
    return new Response(JSON.stringify(routes[key]), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function renderWithSession(ui: ReactNode) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ToastProvider>
        <SessionProvider loading={<p>loading session</p>} error={(e) => <p>session error {String(e)}</p>}>
          {() => ui}
        </SessionProvider>
      </ToastProvider>
    </SWRConfig>,
  );
}
