import { describe, expect, it } from "vitest";
import { presetFor, settingsFor } from "./speedPresets";

describe("speed presets", () => {
  it("round-trips every preset", () => {
    for (const id of ["gentle", "balanced", "fast"] as const)
      expect(presetFor(settingsFor(id))).toBe(id);
  });
  it("the server default is balanced", () => {
    expect(presetFor({ local_concurrency: 1, cloud_concurrency: 3, endpoint_limits: {} })).toBe(
      "balanced",
    );
  });
  it("per-server limits or unnamed numbers are custom", () => {
    expect(
      presetFor({ local_concurrency: 1, cloud_concurrency: 3, endpoint_limits: { a: 2 } }),
    ).toBe("custom");
    expect(presetFor({ local_concurrency: 4, cloud_concurrency: 3, endpoint_limits: {} })).toBe(
      "custom",
    );
  });
});
