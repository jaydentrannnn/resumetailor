import { describe, expect, it } from "vitest";
import { reviewGroup } from "./reviewGroups";

describe("review grouping", () => {
  it("keeps missing verification unknown even with a recorded answer", () => {
    expect(reviewGroup(undefined, { observed_value: "Saved answer" })).toBe("unknown");
    expect(reviewGroup(undefined, { state: "unanswered" })).toBe("unknown");
  });
  it("distinguishes required and optional explicit unanswered fields", () => {
    expect(reviewGroup(undefined, { state: "unanswered", required: true })).toBe("attention");
    expect(reviewGroup(undefined, { state: "unanswered", required: false })).toBe("optional");
  });
  it("preserves generated and retained outcomes", () => {
    expect(reviewGroup(undefined, { state: "verified_filled", answer_source: "generated" })).toBe(
      "generated",
    );
    expect(reviewGroup(undefined, { state: "preserved" })).toBe("verified");
    expect(reviewGroup(undefined, { state: "manual_review" })).toBe("attention");
  });
});
