import { describe, expect, it } from "vitest";
import type { JobBullet, RunHistoryEntry } from "../api";
import { compareCounts, compareRuns, filterRuns, matchesRunQuery, sortRuns } from "./runHistory";

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

describe("filterRuns / sortRuns", () => {
  const run = (over: Partial<RunHistoryEntry>): RunHistoryEntry => ({
    job_id: "x",
    status: "succeeded",
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    title: "Analyst",
    company: "",
    error: null,
    pages: 1,
    coverage_matched: null,
    coverage_total: null,
    has_pdf: true,
    has_docx: true,
    ...over,
  });
  const runs = [
    run({
      job_id: "a",
      title: "Data Analyst",
      company: "Acme",
      created_at: "2026-01-02T00:00:00Z",
      coverage_matched: 1,
      coverage_total: 2,
    }),
    run({
      job_id: "b",
      title: "Engineer",
      company: "Beta",
      status: "failed",
      created_at: "2026-01-03T00:00:00Z",
    }),
    run({
      job_id: "c",
      title: "Analyst",
      company: "Cato",
      status: "running",
      created_at: "2026-01-01T00:00:00Z",
      coverage_matched: 2,
      coverage_total: 2,
    }),
  ];

  it("filters by words and by status", () => {
    expect(filterRuns(runs, "analyst", "").map((r) => r.job_id)).toEqual(["a", "c"]);
    expect(filterRuns(runs, "", "failed").map((r) => r.job_id)).toEqual(["b"]);
    expect(filterRuns(runs, "", "active").map((r) => r.job_id)).toEqual(["c"]);
  });

  it("sorts either way, ties newest first", () => {
    expect(sortRuns(runs, "started", "desc").map((r) => r.job_id)).toEqual(["b", "a", "c"]);
    expect(sortRuns(runs, "company", "asc").map((r) => r.job_id)).toEqual(["a", "b", "c"]);
    expect(sortRuns(runs, "coverage", "desc").map((r) => r.job_id)).toEqual(["c", "a", "b"]);
    // Equal pages: newest first whichever way the column points.
    expect(sortRuns(runs, "pages", "asc").map((r) => r.job_id)).toEqual(["b", "a", "c"]);
  });
});
