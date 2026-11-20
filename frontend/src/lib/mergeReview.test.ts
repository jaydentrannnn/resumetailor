import { describe, expect, it } from "vitest";
import type { MergePair } from "../api";
import {
  changedPicks,
  duplicateTargets,
  pairNote,
  proposedPicks,
  reviewSummary,
} from "./mergeReview";

const pair = (key: string, match: string | null, extra: Partial<MergePair> = {}): MergePair => ({
  key,
  kind: "experience",
  name: key,
  detail: "",
  match,
  match_name: match ? "Existing" : "",
  reason: match ? "same name" : "",
  new_bullets: 2,
  ...extra,
});

const PAIRS = [pair("a", "0:0"), pair("b", null)];

describe("merge review picks", () => {
  it("starts from the proposal", () => {
    expect(proposedPicks(PAIRS)).toEqual({ a: "0:0", b: "new" });
  });

  it("sends only what the student changed", () => {
    expect(changedPicks(PAIRS, { a: "0:0", b: "new" })).toEqual({});
    expect(changedPicks(PAIRS, { a: "new", b: "0:1" })).toEqual({ a: "new", b: "0:1" });
  });

  it("notices two entries pointed at the same existing one", () => {
    expect(duplicateTargets({ a: "0:0", b: "new" })).toBe(false);
    expect(duplicateTargets({ a: "0:0", b: "0:0" })).toBe(true);
  });

  it("summarises what will happen", () => {
    expect(reviewSummary(PAIRS, proposedPicks(PAIRS))).toBe(
      "1 entry will be updated, 1 entry will be added",
    );
    expect(reviewSummary(PAIRS, { a: "new", b: "new" })).toBe("2 entries will be added");
  });

  it("explains each pair", () => {
    expect(pairNote(PAIRS[0], "0:0")).toBe(
      "Proposed because of the same name. 2 new bullets; nothing is removed.",
    );
    expect(pairNote(PAIRS[0], "new")).toBe("Added as a new entry.");
    expect(pairNote(PAIRS[1], "0:0")).toContain("the entry you picked");
  });

  it("points a new entry at the job it may be, without picking it", () => {
    const maybe = pair("c", null, { suggested: "lab", suggested_name: "UCSD Economics Lab" });
    expect(proposedPicks([maybe])).toEqual({ c: "new" });
    expect(pairNote(maybe, "new")).toContain("similar title as UCSD Economics Lab");
    expect(pairNote(maybe, "lab")).toContain("the entry you picked");
    expect(changedPicks([maybe], { c: "lab" })).toEqual({ c: "lab" });
  });
});
