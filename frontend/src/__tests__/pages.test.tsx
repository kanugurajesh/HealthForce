import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fx, mockApi, renderWithSession } from "./harness";

const nav = vi.hoisted(() => ({ params: {} as Record<string, string>, search: "", replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => nav.params,
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ replace: nav.replace, push: nav.push, back: vi.fn() }),
  usePathname: () => "/test",
}));

import CandidatePage from "@/app/(app)/candidates/[id]/page";
import CandidatesPage from "@/app/(app)/candidates/page";
import DocumentPage from "@/app/(app)/documents/[id]/page";
import JobPage from "@/app/(app)/jobs/[id]/page";
import DashboardPage from "@/app/(app)/page";

beforeEach(() => {
  nav.params = {};
  nav.search = "";
  nav.replace.mockReset();
});

describe("dashboard", () => {
  it("renders metrics from API data and links tiles to matching filters", async () => {
    mockApi();
    renderWithSession(<DashboardPage />);
    const tile = await screen.findByRole("link", { name: /credential issues/i });
    expect(tile).toHaveTextContent(String(fx.dashboard.metrics.credential_issues));
    expect(tile.getAttribute("href")).toContain("credential_status=missing,expired,rejected,unable_to_determine");
    expect(screen.getByText("Credential expirations")).toBeInTheDocument();
    expect(screen.getAllByText("Tom Becker").length).toBeGreaterThan(0);
  });
});

describe("candidate list", () => {
  it("shows every candidate with eligibility and review state", async () => {
    mockApi({ "/auth/me": { ...fx.me, role: "recruiter", permissions: ["view", "manage_candidates", "upload_documents"] } });
    renderWithSession(<CandidatesPage />);
    for (const c of fx.candidates.items) expect((await screen.findAllByRole("link", { name: c.full_name })).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Requirement not met").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /add candidate/i })).toBeInTheDocument();
  });

  it("hides recruiter-only actions from roles without permission", async () => {
    mockApi({ "/auth/me": { ...fx.me, role: "viewer", permissions: ["view"] } });
    renderWithSession(<CandidatesPage />);
    await screen.findAllByRole("link", { name: fx.candidates.items[0].full_name });
    expect(screen.queryByRole("button", { name: /add candidate/i })).not.toBeInTheDocument();
  });
});

describe("candidate profile", () => {
  it("explains why a high-scoring candidate is not eligible", async () => {
    mockApi();
    nav.params = { id: fx.candidateTom.id };
    renderWithSession(<CandidatePage />);
    expect(await screen.findByRole("heading", { name: "Tom Becker" })).toBeInTheDocument();
    expect(screen.getAllByText("Requirement not met").length).toBeGreaterThan(0);
    expect(screen.getByText(/Required requirement not met: Registered Nurse/)).toBeInTheDocument();
    expect(screen.getAllByText(/Request renewed Registered Nurse/).length).toBeGreaterThan(0);
  });

  it("shows credential status precedence and the expired license on the credentials tab", async () => {
    mockApi();
    nav.params = { id: fx.candidateTom.id };
    nav.search = "tab=credentials";
    renderWithSession(<CandidatePage />);
    const section = (await screen.findByRole("heading", { name: "Registered Nurse (RN) License" })).closest("section")!;
    expect(within(section).getAllByText("Expired").length).toBeGreaterThan(0);
    expect(within(section).getAllByText(/Primary-source check recorded/).length).toBeGreaterThan(0);
  });

  it("renders the onboarding checklist with progress", async () => {
    mockApi();
    nav.params = { id: fx.candidateMaya.id };
    nav.search = "tab=onboarding";
    renderWithSession(<CandidatePage />);
    expect(await screen.findByText("Final human review")).toBeInTheDocument();
    const done = fx.candidateMaya.tasks.filter((t) => t.status === "done").length;
    expect(screen.getByText(`${done}/${fx.candidateMaya.tasks.length} complete`)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });
});

describe("evidence review", () => {
  it("highlights evidence and focuses the selected claim", async () => {
    mockApi();
    nav.params = { id: fx.documentLicense.id };
    renderWithSession(<DocumentPage />);
    await screen.findByText(fx.documentLicense.original_filename);
    const marks = document.querySelectorAll("mark.evidence");
    expect(marks.length).toBeGreaterThan(0);
    const quote = screen.getAllByRole("button").find((b) => b.textContent?.startsWith("License Type: Registered Nurse"))!;
    fireEvent.click(quote);
    await waitFor(() => expect(document.querySelectorAll("mark.evidence-active").length).toBeGreaterThan(0));
  });

  it("warns about prompt injection and disables bulk acceptance", async () => {
    const { calls } = mockApi();
    nav.params = { id: fx.documentInjection.id };
    renderWithSession(<DocumentPage />);
    expect(await screen.findByText("This document contains instruction-like text (possible prompt injection)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /evidence-supported/i })).not.toBeInTheDocument();
    // Individual review still works and goes to the claim review endpoint.
    fireEvent.click(screen.getAllByRole("button", { name: /^accept$/i })[0]);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && /\/claims\/\w+\/[\w-]+\/review$/.test(c.path))).toBe(true));
  });
});

describe("job matching", () => {
  it("ranks eligible candidates before ineligible ones and explains on demand", async () => {
    mockApi();
    nav.params = { id: fx.jobMatches.job.id };
    renderWithSession(<JobPage />);
    await screen.findByText("Ranked candidates");
    const rows = fx.jobMatches.results;
    const firstNotMet = rows.findIndex((r) => r.match.eligibility === "requirement_not_met");
    const lastEligible = rows.map((r) => r.match.eligibility).lastIndexOf("meets_all_required");
    expect(lastEligible).toBeLessThan(firstNotMet);
    fireEvent.click(screen.getAllByRole("button", { name: /why\?/i })[0]);
    expect(await screen.findByText(/How is the score calculated/)).toBeInTheDocument();
  });
});
