import { describe, expect, it } from "vitest";
import type { JobBullet, RunHistoryEntry } from "../api";
import { compareCounts, compareRuns, matchesRunQuery } from "./runHistory";

const run = (title: string, company = ""): RunHistoryEntry => ({
  job_id: title,
  status: "succeeded",
  created_at: "",
  finished_at: null,
  title,
  company,
  error: null,
  pages: 1,
  coverage_matched: null,
  coverage_total: null,
  has_pdf: false,
  has_docx: false,
});

const bullet = (id: string, entry: string, text: string | null): JobBullet => ({
  bullet_id: id,
  section_title: "Experience",
  entry_label: entry,
  source_text: "src",
  ai_text: text ?? "ai",
  current_text: text,
  merged_from: [],
});

describe("matchesRunQuery", () => {
  it("matches every word against role and company", () => {
    expect(matchesRunQuery(run("Summer Analyst", "Acme Capital"), "acme analyst")).toBe(true);
    expect(matchesRunQuery(run("Summer Analyst", "Acme Capital"), "acme engineer")).toBe(false);
    expect(matchesRunQuery(run("Data Engineer"), "  ")).toBe(true);
  });
});

describe("compareRuns", () => {
  it("classifies each bullet and keeps entry grouping", () => {
    const a = [
      bullet("1", "Acme", "Led X"),
      bullet("2", "Acme", "Built Y"),
      bullet("3", "Beta", "Only A"),
    ];
    const b = [
      bullet("1", "Acme", "Led X"),
      bullet("2", "Acme", "Built Y faster"),
      bullet("4", "Gamma", "Only B"),
    ];
    const groups = compareRuns(a, b);
    expect(groups.map((g) => g.entry)).toEqual(["Acme", "Beta", "Gamma"]);
    expect(groups[0].rows.map((r) => r.kind)).toEqual(["same", "changed"]);
    expect(compareCounts(groups)).toEqual({ same: 1, changed: 1, only_a: 1, only_b: 1 });
  });

  it("treats a bullet removed in review as absent", () => {
    const groups = compareRuns([bullet("1", "Acme", null)], [bullet("1", "Acme", "Kept")]);
    expect(groups[0].rows[0].kind).toBe("only_b");
  });
});
