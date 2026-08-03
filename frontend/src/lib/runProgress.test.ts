import { describe, expect, it } from "vitest";
import type { ProgressEvent } from "../api";
import { runProgress } from "./runProgress";

function ev(stage: string, message = ""): ProgressEvent {
  return { stage, message, detail: {} };
}

/** The stage sequence a clean run emits, in `web/jobs.py` order. */
const CLEAN_RUN = [
  ev("extract"),
  ev("extract"),
  ev("score"),
  ev("facets"),
  ev("fit"),
  ev("rewrite"),
  ev("render"),
  ev("measure"),
  ev("fit"),
  ev("expand"),
];

describe("runProgress", () => {
  it("is indeterminate until the first stage event arrives", () => {
    const p = runProgress([], "queued", true);
    expect(p.indeterminate).toBe(true);
    expect(p.label).toBe("Queued");
  });

  it("reads zero when nothing is running", () => {
    expect(runProgress([], null, false)).toMatchObject({ value: 0, indeterminate: false });
  });

  it("advances monotonically through a clean run", () => {
    let previous = -1;
    for (let i = 1; i <= CLEAN_RUN.length; i++) {
      const { value } = runProgress(CLEAN_RUN.slice(0, i), "running", true);
      expect(value).toBeGreaterThanOrEqual(previous);
      previous = value;
    }
  });

  it("never rewinds when a late render event follows expand", () => {
    // jobs.py emits stage "render" (fit band) after "expand" when PDF preview fails.
    const during = runProgress([...CLEAN_RUN], "running", true).value;
    const after = runProgress([...CLEAN_RUN, ev("render", "PDF preview unavailable")], "running", true);
    expect(after.value).toBeGreaterThanOrEqual(during);
  });

  it("creeps within the fit band per measured iteration without leaving it", () => {
    const upto = CLEAN_RUN.slice(0, 8); // …through the first `measure`
    const one = runProgress(upto, "running", true).value;
    const three = runProgress(
      [...upto, ev("rewrite"), ev("measure"), ev("rewrite"), ev("measure")],
      "running",
      true,
    ).value;
    expect(three).toBeGreaterThan(one);
    expect(three).toBeLessThan(0.88);
  });

  it("reads 100% on a finished run even when expansion was skipped", () => {
    const noExpand = CLEAN_RUN.slice(0, -1);
    expect(runProgress(noExpand, "succeeded", false).value).toBe(1);
    expect(runProgress(noExpand, "failed", false)).toMatchObject({ value: 1, label: "Failed" });
  });

  it("holds position on an unrecognised stage rather than rewinding", () => {
    const known = runProgress(CLEAN_RUN.slice(0, 4), "running", true).value;
    const withUnknown = runProgress(
      [...CLEAN_RUN.slice(0, 4), ev("brand-new-stage")],
      "running",
      true,
    );
    expect(withUnknown.value).toBe(known);
    expect(withUnknown.indeterminate).toBe(false);
  });
});
