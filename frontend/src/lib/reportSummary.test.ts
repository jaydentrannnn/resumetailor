import { describe, expect, it } from "vitest";
import type { KeywordGap, RunReport } from "../api";
import { describeEvidence, gapGroups, missingSummary, reportHeadline } from "./reportSummary";

const gap = (
  phrase: string,
  reason: KeywordGap["reason"],
  evidence: string[] = [],
  band?: string,
  importance: KeywordGap["importance"] = "must_have",
): KeywordGap => ({
  canonical: phrase.toLowerCase(),
  phrase,
  importance,
  reason,
  evidence,
  band,
});

const report = (over: Partial<RunReport> = {}): RunReport =>
  ({
    coverage_matched: 8,
    coverage_total: 10,
    pages: 1,
    pages_are_estimated: false,
    extraction_diagnosis: null,
    gaps: [],
    missing_must_haves: [],
    ...over,
  }) as RunReport;

describe("report summary", () => {
  it("writes a one-line headline", () => {
    expect(reportHeadline(report())).toBe("Matched 8 of 10 required skills · 1 page");
    expect(reportHeadline(report({ pages: 2, pages_are_estimated: true }))).toBe(
      "Matched 8 of 10 required skills · 2 pages (estimated)",
    );
    expect(reportHeadline(report({ extraction_diagnosis: "no_must_haves" }))).toContain(
      "couldn't be measured",
    );
    expect(reportHeadline(report({ coverage_total: 0 }))).toContain("No required skills");
  });

  it("explains where evidence was found", () => {
    expect(describeEvidence(`project tech 'p1': "SQL"`)).toBe(
      `listed as "SQL" in a project's tech`,
    );
    expect(describeEvidence(`skills 'Tools': "Excel"`)).toBe(
      `listed as "Excel" under Tools skills`,
    );
    expect(describeEvidence(`coursework: "Corporate Finance"`)).toBe(
      `in your coursework as "Corporate Finance"`,
    );
    expect(describeEvidence(`bullet tag: "ml"`)).toBe(`a bullet shows "ml"`);
    expect(describeEvidence("something new")).toBe("something new");
  });

  it("groups gaps by what the student can do, most important first", () => {
    const groups = gapGroups(
      report({
        gaps: [
          gap("Tableau", "no_evidence", [], "preferred"),
          gap("DCF", "no_evidence", [], "critical"),
          gap("SQL", "untagged_evidence", [`skills 'Tools': "SQL"`]),
          gap("Machine learning", "near_miss", [`bullet tag: "ml"`]),
        ],
        missing_must_haves: ["DCF", "CFA"],
      }),
    );
    expect(groups.missing.map((m) => m.phrase)).toEqual(["DCF", "Tableau", "CFA"]);
    expect(groups.untagged).toEqual([
      { phrase: "SQL", where: [`listed as "SQL" under Tools skills`] },
    ]);
    expect(groups.renamed[0].where[0]).toBe(`a bullet shows "ml"`);
  });

  it("marks required skills by importance, not band, lists them first, and never twice", () => {
    const groups = gapGroups(
      report({
        gaps: [
          gap("Tableau", "no_evidence", [], "critical", "nice_to_have"),
          gap("Excel", "no_evidence", [], "meaningful", "must_have"),
          gap("SQL", "untagged_evidence", [`skills 'Tools': "SQL"`], "high", "must_have"),
          gap("Looker", "no_evidence", [], "preferred", "nice_to_have"),
        ],
        missing_must_haves: ["Excel", "SQL"],
      }),
    );
    expect(groups.missing.map((m) => [m.phrase, m.required])).toEqual([
      ["Excel", true],
      ["Tableau", false],
      ["Looker", false],
    ]);
    expect(groups.untagged.map((u) => u.phrase)).toEqual(["SQL"]);
    expect(missingSummary(groups)).toBe(
      "1 required and 2 nice-to-have skills aren't on your resume",
    );
    expect(missingSummary({ missing: [], untagged: [], renamed: [] })).toBeNull();
  });
});
