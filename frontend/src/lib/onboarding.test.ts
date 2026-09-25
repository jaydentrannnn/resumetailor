import { describe, expect, it } from "vitest";
import type { OnboardingState, SourceConfig } from "../api";
import {
  ONBOARDING_STEPS,
  needsWelcome,
  packsForField,
  reviewResume,
  sourcesForField,
  stepIndex,
} from "./onboarding";
import type { MasterResume } from "./resumeEdit";

const SOURCES: SourceConfig[] = [
  {
    id: "simplify-internships",
    kind: "simplify_html",
    url: "u1",
    categories: ["A"],
    enabled: true,
  },
  { id: "simplify-newgrad", kind: "simplify_html", url: "u2", categories: ["B"], enabled: true },
  { id: "speedyapply", kind: "pipe_table", url: "u3", categories: ["C"], enabled: true },
  { id: "mine", kind: "pipe_table", url: "u4", categories: ["D"], enabled: true },
];

const state = (over: Partial<OnboardingState> = {}): OnboardingState => ({
  step: "field",
  field: "",
  completed: false,
  skipped: false,
  updated_at: "",
  ...over,
});

describe("onboarding helpers", () => {
  it("orders the steps", () => {
    expect(stepIndex("field")).toBe(0);
    expect(stepIndex("done")).toBe(ONBOARDING_STEPS.length - 1);
  });

  it("swaps field packs but keeps packs the user added", () => {
    const available = ["core-tech", "finance-consulting", "custom"];
    expect(packsForField(["core-tech", "custom"], "business", available)).toEqual([
      "core-tech",
      "finance-consulting",
      "custom",
    ]);
    expect(packsForField(["core-tech", "finance-consulting"], "cs", available)).toEqual([
      "core-tech",
    ]);
    // A pack missing from this install is skipped, not enabled by id.
    expect(packsForField([], "business", ["core-tech"])).toEqual(["core-tech"]);
    expect(packsForField(["x"], "", available)).toEqual(["x"]);
  });

  it("points business students at finance and product boards", () => {
    const out = sourcesForField(SOURCES, "business");
    expect(out[0].categories).toEqual([
      "Quantitative Finance Internship Roles",
      "Product Management Internship Roles",
    ]);
    expect(out[1].categories[0]).toBe("Quantitative Finance New Grad Roles");
    expect(out[2].enabled).toBe(false);
    expect(out[3]).toBe(SOURCES[3]);
    expect(sourcesForField(SOURCES, "other")).toBe(SOURCES);
  });

  it("summarises the resume and flags gaps", () => {
    const resume: MasterResume = {
      contact: { name: "Your Name", email: "you@example.com" },
      sections: [
        {
          id: "s1",
          title: "Experience",
          kind: "experience",
          entries: [
            {
              id: "e1",
              company: "Acme",
              title: "Analyst",
              start: "",
              end: "",
              bullets: [{ id: "b1", text: "Did it", tags: [] }],
            },
          ],
        },
        {
          id: "s2",
          title: "Projects",
          kind: "project",
          entries: [{ id: "p1", name: "Model", bullets: [] }],
        },
      ],
    } as unknown as MasterResume;
    const review = reviewResume(resume);
    expect(review.entries).toBe(2);
    expect(review.bullets).toBe(1);
    expect(review.warnings).toEqual([
      "Your name is missing.",
      "No dates found for Acme.",
      "Model has no bullets.",
      "1 bullet has no skill tags; untagged bullets rank lower for every job.",
    ]);
    expect(reviewResume(null).entries).toBe(0);
  });

  it("redirects only an unfinished profile, never from Settings", () => {
    expect(needsWelcome(state(), "/")).toBe(true);
    expect(needsWelcome(state(), "/settings")).toBe(false);
    expect(needsWelcome(state(), "/welcome")).toBe(false);
    expect(needsWelcome(state({ skipped: true }), "/")).toBe(false);
    expect(needsWelcome(state({ completed: true }), "/")).toBe(false);
    expect(needsWelcome(null, "/")).toBe(false);
  });
});
