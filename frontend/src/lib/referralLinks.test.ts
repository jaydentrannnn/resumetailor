import { describe, expect, it } from "vitest";
import { referralSearches, roleKeyword } from "./referralLinks";

describe("roleKeyword", () => {
  it("keeps the job and drops terms, dates and places", () => {
    expect(roleKeyword("Data Analyst Intern (Summer 2026) - New York")).toBe("Data Analyst");
    expect(roleKeyword("Software Engineer II, Payments")).toBe("Software Engineer");
    expect(roleKeyword("Summer 2026 Investment Banking Analyst")).toBe(
      "Investment Banking Analyst",
    );
    expect(roleKeyword("Intern")).toBe("");
  });
});

describe("referralSearches", () => {
  it("builds encoded people searches for recruiters and the role", () => {
    const [recruiters, peers] = referralSearches("AT&T", "Data Analyst Intern");
    expect(recruiters).toEqual({
      label: "Recruiters at AT&T",
      url: "https://www.linkedin.com/search/results/people/?keywords=AT%26T%20recruiter",
    });
    expect(peers.label).toBe("Data Analyst at AT&T");
    expect(peers.url).toContain("keywords=AT%26T%20Data%20Analyst");
  });

  it("offers only the recruiter search when the title has no job words", () => {
    expect(referralSearches("Acme", "Intern")).toHaveLength(1);
    expect(referralSearches("  ", "Analyst")).toEqual([]);
  });
});
