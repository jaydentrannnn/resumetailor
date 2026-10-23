import { describe, expect, it } from "vitest";
import type { CoverageFunnel } from "../api";
import { fitChecks, pageStrengths } from "./fitSummary";

describe("pageStrengths", () => {
  it("lists the must-haves the page shows, in posting order", () => {
    const funnel = {
      total: 4,
      in_resume: 3,
      on_page: 2,
      keywords: [
        { canonical: "sql", phrase: "SQL", resume: "stated", page: "expressed" },
        { canonical: "go", phrase: "Go", resume: null, page: null },
        { canonical: "teamwork", phrase: "Teamwork", resume: "stated", page: "demonstrated" },
        { canonical: "aws", phrase: "AWS", resume: "tagged", page: "not_selected" },
      ],
      unsupported_additions: [],
    } as CoverageFunnel;
    expect(pageStrengths(funnel)).toEqual(["SQL", "Teamwork"]);
    expect(pageStrengths(null)).toEqual([]);
  });
});

describe("fitChecks", () => {
  it("words each known flag once and drops codes with no note", () => {
    const notes = fitChecks({
      eligibility_flags: ["years_2", "age_unknown", "language_unlisted:Spanish"],
      screen: {
        flags: ["years_2", "language_level:German", "enrollment wording matched '\\benrolled'"],
      } as never,
    });
    expect(notes).toEqual([
      "The posting asks for 2+ years of experience.",
      "The posting requires Spanish. Add your languages in Profile so this can be checked.",
      "The posting asks for fluent German; your profile lists German as not fluent.",
      "The posting asks that you be enrolled in school.",
    ]);
    expect(fitChecks({ eligibility_flags: [], screen: null })).toEqual([]);
  });
});
