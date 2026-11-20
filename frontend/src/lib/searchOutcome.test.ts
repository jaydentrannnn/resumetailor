import { describe, expect, it } from "vitest";
import type { SourceConfig, SourceRunStatus, SourcesStatus } from "../api";
import { outcomeCopy, searchOutcome } from "./searchOutcome";

const source = (id: string, enabled = true): SourceConfig => ({
  id,
  kind: "pipe_table",
  url: "",
  categories: [],
  enabled,
});
const run = (found: number, kept: number, error: string | null = null): SourceRunStatus => ({
  found,
  kept,
  error,
  at: "2026-11-17T10:00:00Z",
});
const status = (runs: Record<string, SourceRunStatus>): SourcesStatus => ({
  sources: runs,
  last_run_at: "2026-11-17T10:00:00Z",
});
const SOURCES = [source("a"), source("b"), source("off", false)];

describe("searchOutcome", () => {
  it("knows nothing before a switched-on list has run", () => {
    expect(searchOutcome(SOURCES, null)).toEqual({ kind: "unknown" });
    expect(searchOutcome(SOURCES, status({ off: run(9, 9) }))).toEqual({ kind: "unknown" });
  });

  it("tells failed lists, empty lists, filtered postings and nothing new apart", () => {
    expect(
      searchOutcome(SOURCES, status({ a: run(0, 0, "HTTP 401"), b: run(0, 0, "timeout") })),
    ).toEqual({ kind: "failed", lists: 2, error: "HTTP 401" });
    expect(searchOutcome(SOURCES, status({ a: run(0, 0), b: run(0, 0, "HTTP 500") }))).toEqual({
      kind: "empty",
      lists: 2,
      failed: 1,
    });
    expect(searchOutcome(SOURCES, status({ a: run(40, 0), b: run(3, 0) }))).toEqual({
      kind: "filtered",
      found: 43,
      failed: 0,
    });
    expect(searchOutcome(SOURCES, status({ a: run(40, 5), b: run(3, 0) }))).toEqual({
      kind: "nothing_new",
      kept: 5,
      failed: 0,
    });
  });

  it("reads the server's 'No postings found' as an empty list, not a failure", () => {
    expect(searchOutcome(SOURCES, status({ a: run(0, 0, "No postings found") }))).toEqual({
      kind: "empty",
      lists: 1,
      failed: 0,
    });
  });

  it("does not count 'found nothing useful' on a list with postings as a failure", () => {
    expect(searchOutcome(SOURCES, status({ a: run(12, 0, "every row lacked a title") }))).toEqual({
      kind: "filtered",
      found: 12,
      failed: 0,
    });
  });
});

describe("outcomeCopy", () => {
  it("words each outcome for a student", () => {
    expect(outcomeCopy({ kind: "unknown" })).toBeNull();
    expect(outcomeCopy({ kind: "failed", lists: 1, error: "HTTP 401" })?.detail).toBe(
      "The list failed on the last search: HTTP 401.",
    );
    expect(outcomeCopy({ kind: "filtered", found: 43, failed: 1 })?.detail).toContain(
      "found 43 postings, and the filters",
    );
    expect(outcomeCopy({ kind: "filtered", found: 43, failed: 1 })?.detail).toContain(
      "1 list also failed",
    );
    expect(outcomeCopy({ kind: "nothing_new", kept: 1, failed: 0 })?.detail).toMatch(
      /^1 posting passed/,
    );
  });
});
