import { describe, expect, it } from "vitest";
import { presetFor, settingsFor, withSpeedPreset } from "./speedPresets";

describe("speed presets", () => {
  it("restores custom limits across presets and reload, even when they match a preset", () => {
    const custom = {
      ...settingsFor("balanced"),
      custom_mode: true,
      endpoint_limits: { "https://proxy.example/api": 7 },
    };
    const balanced = withSpeedPreset(custom, "balanced");
    expect(balanced.endpoint_limits).toEqual({});
    const restored = withSpeedPreset(JSON.parse(JSON.stringify(balanced)), "custom");
    expect(restored.endpoint_limits).toEqual(custom.endpoint_limits);
    expect(presetFor(withSpeedPreset(settingsFor("balanced"), "custom"))).toBe("custom");
  });
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
