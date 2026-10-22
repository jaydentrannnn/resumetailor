import { describe, expect, it } from "vitest";
import { heatFill, heatmapAxes } from "./progressOptions";

describe("heatmapAxes", () => {
  it("transposes when there are fewer than 7 weeks", () => {
    expect(heatmapAxes(4)).toEqual({ transpose: true });
    expect(heatmapAxes(6)).toEqual({ transpose: true });
    expect(heatmapAxes(7)).toEqual({ transpose: false });
    expect(heatmapAxes(13)).toEqual({ transpose: false });
  });
});

describe("heatFill", () => {
  it("always uses the accent color", () => {
    expect(heatFill(4)).toContain("var(--color-accent)");
    expect(heatFill(2)).toContain("45%");
  });
});
