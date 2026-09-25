import { describe, expect, it } from "vitest";
import type { ProgressEvent, RunHistoryEntry } from "../api";
import { hostOf, wordCount } from "./jdInput";
import { formatElapsed, formatTypical, runSteps, typicalRunSeconds } from "./runSteps";

const ev = (stage: string): ProgressEvent => ({ stage, message: "", detail: {} });
const run = (status: RunHistoryEntry["status"], secs: number | null): RunHistoryEntry => ({
  job_id: "j",
  status,
  created_at: "2026-01-01T00:00:00Z",
  finished_at:
    secs == null ? null : new Date(Date.parse("2026-01-01T00:00:00Z") + secs * 1000).toISOString(),
  title: "",
  error: null,
  pages: 1,
  coverage_matched: null,
  coverage_total: null,
  has_pdf: true,
  has_docx: true,
});

describe("runSteps", () => {
  it("follows the furthest stage and never rewinds", () => {
    const state = runSteps(
      [ev("extract"), ev("score"), ev("rewrite"), ev("measure"), ev("rewrite")],
      "running",
      false,
    );
    expect(state.steps[state.current].label).toBe("Fitting to the page");
    expect(state.failed).toBeNull();
  });
  it("does not jump ahead on the job-start event or the pre-rewrite fit event", () => {
    const early = runSteps([ev("start")], "running", false);
    expect(early.current).toBe(0);
    const state = runSteps(
      [ev("start"), ev("extract"), ev("score"), ev("facets"), ev("fit"), ev("rewrite")],
      "running",
      false,
    );
    expect(state.steps[state.current].label).toBe("Rewriting bullets");
    const fitting = runSteps(
      [ev("start"), ev("extract"), ev("fit"), ev("rewrite"), ev("render")],
      "running",
      false,
    );
    expect(fitting.steps[fitting.current].label).toBe("Fitting to the page");
  });
  it("marks all done on success and the current step on failure", () => {
    expect(runSteps([ev("extract")], "succeeded", false).current).toBe(6);
    expect(runSteps([ev("extract"), ev("score")], "failed", false).failed).toBe(1);
    expect(runSteps([], "queued", false).current).toBe(0);
  });
  it("names the last step after the cover letter when one is on", () => {
    expect(runSteps([], null, true).steps[5].label).toBe("Writing cover letter");
    expect(runSteps([ev("unknown")], null, false).current).toBe(0);
  });
});

describe("time estimates", () => {
  it("uses the median of recent successful runs", () => {
    expect(
      typicalRunSeconds([
        run("succeeded", 60),
        run("failed", 5),
        run("succeeded", 120),
        run("succeeded", 90),
      ]),
    ).toBe(90);
    expect(typicalRunSeconds([run("succeeded", 60), run("succeeded", 100)])).toBe(80);
    expect(typicalRunSeconds([run("succeeded", 60), run("running", null)])).toBeNull();
  });
  it("formats", () => {
    expect(formatElapsed(45)).toBe("45s");
    expect(formatElapsed(125)).toBe("2m 05s");
    expect(formatTypical(30)).toBe("under a minute");
    expect(formatTypical(100)).toBe("about 2 min");
  });
});

describe("jd input helpers", () => {
  it("counts words and reads hosts", () => {
    expect(wordCount("  Analyst  intern\nNew York ")).toBe(4);
    expect(wordCount("   ")).toBe(0);
    expect(hostOf("https://www.example.com/jobs/1")).toBe("example.com");
    expect(hostOf("nonsense")).toBe("");
  });
});
