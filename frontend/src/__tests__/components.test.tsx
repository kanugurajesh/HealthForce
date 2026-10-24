import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MatchBreakdown } from "@/components/match";
import { CredentialStatusBadge, EligibilityBadge } from "@/components/status";
import { ApiError } from "@/lib/api";
import { formatDate, relativeDays } from "@/lib/format";
import type { Match } from "@/lib/types";

const match: Match = {
  job: { id: "j", title: "ICU RN" },
  score: 64,
  eligibility: "missing_information",
  eligibility_explanation: "Missing information for: ACLS.",
  score_explanation: "Score = weighted points earned / possible.",
  satisfied: 1,
  not_satisfied: 0,
  pending: 0,
  unknown: 1,
  requirements: [
    { requirement_id: "a", kind: "credential", label: "RN License", is_required: true, weight: 5, outcome: "met", explanation: "Verified.", points_earned: 5, points_possible: 5, next_action: null, evidence: [] },
    { requirement_id: "b", kind: "credential", label: "ACLS", is_required: true, weight: 3, outcome: "unknown", explanation: "No ACLS on file.", points_earned: 0, points_possible: 3, next_action: "Request ACLS.", evidence: [] },
  ],
  next_actions: [],
};

describe("status badges", () => {
  it("labels simulated verification explicitly", () => {
    render(<CredentialStatusBadge status="verified" simulated />);
    expect(screen.getByText("Verified (simulated)")).toBeInTheDocument();
  });

  it("uses text, not only colour", () => {
    render(<EligibilityBadge value="requirement_not_met" />);
    expect(screen.getByText("Requirement not met")).toBeInTheDocument();
  });
});

describe("MatchBreakdown", () => {
  it("expands unmet requirements by default and shows the next step", () => {
    render(<MatchBreakdown match={match} />);
    expect(screen.getByText("No ACLS on file.")).toBeInTheDocument();
    expect(screen.getByText("Next step: Request ACLS.")).toBeInTheDocument();
    expect(screen.queryByText("Verified.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /RN License/ }));
    expect(screen.getByText("Verified.")).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("formats dates without timezone drift", () => {
    expect(formatDate("2027-03-31")).toBe("Mar 31, 2027");
    expect(relativeDays(-3)).toBe("3 days ago");
  });

  it("surfaces API blockers as readable lines", () => {
    const e = new ApiError(409, "conflict", "Blocked", { blockers: ["ACLS missing"] });
    expect(e.detailLines).toEqual(["ACLS missing"]);
  });
});
