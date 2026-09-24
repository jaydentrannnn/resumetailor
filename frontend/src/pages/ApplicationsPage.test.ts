import { describe, expect, it } from "vitest";
import { describePhase, runProgressPercent, sumStatusCounts } from "./ApplicationsPage";

describe("sumStatusCounts", () => {
  it("sums chip counts", () => {
    expect(sumStatusCounts({ ready: 2, submitted: 3 })).toBe(5);
    expect(sumStatusCounts({})).toBe(0);
  });
});

describe("runProgressPercent", () => {
  it("clamps to 0-100 and handles an unknown total", () => {
    expect(runProgressPercent(0, 10)).toBe(0);
    expect(runProgressPercent(5, 10)).toBe(50);
    expect(runProgressPercent(10, 10)).toBe(100);
    expect(runProgressPercent(99, 10)).toBe(100);
    expect(runProgressPercent(-1, 10)).toBe(0);
    expect(runProgressPercent(3, 0)).toBe(0);
    expect(runProgressPercent(3, NaN)).toBe(0);
  });
});

describe("describePhase", () => {
  it("is empty without a status", () => {
    expect(describePhase(null)).toBe("");
  });

  it("describes discovery and processing phases while running", () => {
    expect(
      describePhase({
        running: true,
        phase: "discovering",
        source_id: "simplify-newgrad",
        current: "",
        processed: 0,
        total: 0,
        dry_run: false,
        started_at: "",
        finished_at: "",
        date: "",
        summary: null,
      }),
    ).toBe("Fetching source simplify-newgrad…");

    expect(
      describePhase({
        running: true,
        phase: "processing",
        source_id: "simplify-internships",
        current: "Acme — Software Intern",
        processed: 1,
        total: 4,
        dry_run: false,
        started_at: "",
        finished_at: "",
        date: "",
        summary: null,
      }),
    ).toBe("Processing 2/4: Acme — Software Intern");
  });

  it("reports a finished run and a skipped run", () => {
    expect(
      describePhase({
        running: false,
        phase: "done",
        source_id: "",
        current: "",
        processed: 0,
        total: 0,
        dry_run: true,
        started_at: "",
        finished_at: "",
        date: "",
        summary: null,
      }),
    ).toBe("Last run finished (dry run)");

    expect(
      describePhase({
        running: false,
        phase: "done",
        source_id: "",
        current: "",
        processed: 0,
        total: 0,
        dry_run: false,
        fetch_only: true,
        started_at: "",
        finished_at: "",
        date: "",
        summary: null,
      }),
    ).toBe("Last run finished (fetch only)");

    expect(
      describePhase({
        running: true,
        phase: "processing",
        source_id: "simplify-internships",
        current: "Acme — Software Intern",
        processed: 0,
        total: 2,
        dry_run: false,
        fetch_only: true,
        started_at: "",
        finished_at: "",
        date: "",
        summary: null,
      }),
    ).toBe("Recording 1/2: Acme — Software Intern");
  });
});
