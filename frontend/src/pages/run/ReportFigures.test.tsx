// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { RunReport } from "../../api";
import { ReportFigures } from "./ReportFigures";

afterEach(cleanup);

const base = {
  title: "Engineer",
  seniority: "entry",
  coverage_matched: 12,
  coverage_total: 14,
  missing_must_haves: [],
  unmatched_canonicals: [],
  gaps: [],
  model: "m",
  semantic_used: true,
  bullets_selected: 14,
  bullets_total: 19,
  experience: [],
  projects: [],
  dropped: [],
  pages: 1,
  pages_are_estimated: false,
  iterations: 1,
  widows_repaired: 0,
  widows_remaining: 0,
  verbs_diversified: 0,
  verb_collisions_remaining: 0,
  warnings: [],
  out_path: "",
} as unknown as RunReport;

it("shows two figures: the tailored page and the main resume as written", () => {
  const report = {
    ...base,
    page_coverage_matched: 9,
    coverage_funnel: {
      total: 14,
      in_resume: 12,
      on_page: 9,
      in_resume_text: 7,
      keywords: [],
      unsupported_additions: [],
    },
  } as RunReport;
  render(<ReportFigures report={report} />);
  expect(screen.getByText("64%")).toBeTruthy();
  expect(screen.getByText("9 of 14 on the tailored page")).toBeTruthy();
  expect(screen.getByText("7 of 14 mentioned in your main resume")).toBeTruthy();
  // The tag-backed resume figure is no longer a third line.
  expect(screen.queryByText("12 of 14 in your resume")).toBeNull();
});

it("shows only the page figure on a run saved before the main-resume figure", () => {
  render(<ReportFigures report={{ ...base, page_coverage_matched: 9 } as RunReport} />);
  expect(screen.getByText("9 of 14 on the tailored page")).toBeTruthy();
  expect(screen.queryByText("12 of 14 in your resume")).toBeNull();
  expect(screen.queryByText(/main resume/)).toBeNull();
});

it("falls back to the resume figure on a run saved before page coverage", () => {
  render(<ReportFigures report={base} />);
  expect(screen.getByText("86%")).toBeTruthy();
  expect(screen.getByText("12 of 14 in your resume")).toBeTruthy();
  expect(screen.queryByText(/on the tailored page/)).toBeNull();
  expect(screen.queryByText(/main resume/)).toBeNull();
});
