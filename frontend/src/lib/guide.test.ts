import { describe, expect, it } from "vitest";
import type { SetupStatus } from "../api";
import { guideActive, guidePillLabel, guideProgress, guideSteps, type GuideInputs } from "./guide";

const READY: SetupStatus = { items: [], ready: true, remaining: 0 };

const inputs = (over: Partial<GuideInputs> = {}): GuideInputs => ({
  setup: READY,
  runs: 0,
  applyDone: false,
  progress: { found: 0, autofilled: 0, sent_total: 0 },
  ...over,
});

const doneIds = (over: Partial<GuideInputs> = {}) =>
  guideSteps(inputs(over))
    .filter((step) => step.done)
    .map((step) => step.id);

describe("getting started guide", () => {
  it("lists the six steps in the order a new student does them", () => {
    expect(guideSteps(inputs()).map((step) => step.id)).toEqual([
      "setup",
      "tailor",
      "apply_setup",
      "find",
      "fill",
      "send",
    ]);
  });

  it("ticks each step from what the app already knows", () => {
    expect(doneIds()).toEqual(["setup"]);
    expect(doneIds({ runs: 1 })).toEqual(["setup", "tailor"]);
    expect(doneIds({ applyDone: true })).toEqual(["setup", "apply_setup"]);
    expect(doneIds({ progress: { found: 3, autofilled: 1, sent_total: 0 } })).toEqual([
      "setup",
      "find",
      "fill",
    ]);
    expect(doneIds({ progress: { found: 3, autofilled: 1, sent_total: 1 } })).toContain("send");
  });

  it("sends Finish setup to the first required thing still missing", () => {
    const setup: SetupStatus = {
      ready: false,
      remaining: 1,
      items: [
        {
          id: "calibration",
          label: "Page fit",
          ok: false,
          detail: "Using estimates.",
          fix: { label: "Tune page fit", to: "/template" },
          optional: true,
        },
        {
          id: "model",
          label: "AI model",
          ok: false,
          detail: "An API key is missing.",
          fix: { label: "Add your key", to: "/settings" },
          optional: false,
        },
      ],
    };
    const [first] = guideSteps(inputs({ setup }));
    expect(first).toMatchObject({
      done: false,
      to: "/settings",
      action: "Add your key",
      detail: "AI model: An API key is missing.",
    });
  });

  it("counts progress and names the next open step", () => {
    const steps = guideSteps(inputs({ runs: 2 }));
    expect(guideProgress(steps)).toMatchObject({ done: 2, total: 6 });
    expect(guideProgress(steps).next?.id).toBe("apply_setup");
    expect(guidePillLabel(steps)).toBe("Get started · 2/6");
  });

  it("shows until it is hidden or everything is done", () => {
    const open = guideSteps(inputs());
    const finished = guideSteps(
      inputs({ runs: 1, applyDone: true, progress: { found: 1, autofilled: 1, sent_total: 1 } }),
    );
    expect(guideActive(false, open)).toBe(true);
    expect(guideActive(true, open)).toBe(false);
    expect(guideActive(false, finished)).toBe(false);
    expect(guideProgress(finished).next).toBeNull();
    expect(guideActive(false, null)).toBe(false);
  });
});
