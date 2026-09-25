import { describe, expect, it } from "vitest";
import { evidenceTime } from "./submitEvidence";

describe("evidenceTime", () => {
  it("reads the UTC stamp of a submit folder", () => {
    const expected = new Date(Date.UTC(2026, 8, 25, 12, 30, 5)).toLocaleString();
    expect(evidenceTime("submit-20260925T123005Z")).toBe(expected);
  });

  it("returns anything else unchanged", () => {
    expect(evidenceTime("submit-latest")).toBe("submit-latest");
  });
});
