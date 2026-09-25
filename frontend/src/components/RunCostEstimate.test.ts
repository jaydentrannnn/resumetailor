import { describe, expect, it } from "vitest";
import type { RunEstimate } from "../api";
import { describeEstimate } from "./RunCostEstimate";

const base: RunEstimate = {
  calls: 8,
  input_tokens: 20000,
  output_tokens: 4000,
  usd: 0.042,
  local: false,
  stages: [],
};

describe("describeEstimate", () => {
  it("hides the line for local models and missing estimates", () => {
    expect(describeEstimate(null)).toBeNull();
    expect(describeEstimate({ ...base, local: true, usd: 0 })).toBeNull();
  });
  it("shows dollars when every stage is priced", () => {
    expect(describeEstimate(base)).toBe(
      "About 8 model calls, about $0.04 on your API key. Repeat runs of a posting cost less.",
    );
    expect(describeEstimate({ ...base, usd: 0.004 })).toContain("under $0.01");
  });
  it("falls back to tokens when a price is unknown", () => {
    expect(describeEstimate({ ...base, usd: null })).toBe(
      "About 8 model calls, ~24k tokens (price unknown for this model)",
    );
  });
});
