import { describe, expect, it } from "vitest";
import { entryCount, readSummary, resumeTotals } from "./readSummary";

const section = (key: string, heading_text: string, entry_count: number, bullet_count: number) => ({
  key,
  heading_text,
  entry_count,
  bullet_count,
});

describe("readSummary", () => {
  it("names each section's entries and counts its bullets", () => {
    expect(
      readSummary([
        section("education", "EDUCATION", 1, 0),
        section("experience", "WORK EXPERIENCE", 2, 5),
        section("projects", "Projects", 1, 1),
        section("skills", "SKILLS", 3, 0),
        section("leadership", " ", 2, 0),
      ]),
    ).toEqual([
      { title: "EDUCATION", detail: "1 school" },
      { title: "WORK EXPERIENCE", detail: "2 jobs, 5 bullets" },
      { title: "Projects", detail: "1 project, 1 bullet" },
      { title: "SKILLS", detail: "3 groups" },
      { title: "leadership", detail: "2 entries" },
    ]);
  });
});

describe("entryCount", () => {
  it("adds up every section's entries", () => {
    expect(entryCount(null)).toBe(0);
    expect(entryCount({ sections: [{ entries: [1, 2] }, { entries: [] }, { entries: [3] }] })).toBe(
      3,
    );
  });
});

describe("resumeTotals", () => {
  const entry = (bullets: number) => ({ bullets: Array.from({ length: bullets }) });

  it("counts jobs, projects and bullets", () => {
    expect(
      resumeTotals({
        sections: [
          { kind: "education", entries: [entry(0)] },
          { kind: "experience", entries: [entry(3), entry(2)] },
          { kind: "project", entries: [entry(1)] },
          { kind: "skills", entries: [{}, {}] },
        ],
      }),
    ).toBe("2 jobs, 1 project and 6 bullets");
  });

  it("leaves out what is not there", () => {
    expect(resumeTotals({ sections: [{ kind: "experience", entries: [entry(0)] }] })).toBe("1 job");
    expect(resumeTotals({ sections: [{ kind: "skills", entries: [{}] }] })).toBe("");
    expect(resumeTotals(null)).toBe("");
  });
});
