import { describe, expect, it } from "vitest";
import type {
  ApplySettings,
  CatalogEntry,
  OnboardingState,
  SourceCatalog,
  SourceConfig,
} from "../api";
import {
  ONBOARDING_STEPS,
  needsWelcome,
  packsForField,
  reviewResume,
  sourceFieldsFor,
  sourcesForField,
  sourcesFromCatalogPicks,
  suggestedEntries,
  stepIndex,
  withSourceChoice,
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
    const shipped = [
      "core-tech",
      "finance-consulting",
      "accounting",
      "marketing",
      "ops-supply-chain",
    ];
    expect(packsForField(["core-tech"], "business", shipped)).toEqual(shipped);
    // Switching away from Business turns every business pack off again.
    expect(packsForField(shipped, "cs", shipped)).toEqual(["core-tech"]);
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
    expect(out[4]).toMatchObject({ kind: "ats_board", boards: [], enabled: true });
    // Choosing business again never adds a second watchlist.
    expect(sourcesForField(out, "business").filter((s) => s.kind === "ats_board")).toHaveLength(1);
    expect(sourcesForField(SOURCES, "cs").some((s) => s.kind === "ats_board")).toBe(false);
    expect(sourcesForField(SOURCES, "other")).toBe(SOURCES);
  });

  it("maps a study field to catalog entries and writes them as the sources", () => {
    const entry = (id: string, fields: CatalogEntry["fields"]): CatalogEntry => ({
      id,
      name: id,
      description: "",
      fields,
      version: "1",
      template: { id, kind: "pipe_table", url: `u-${id}`, categories: [], enabled: true },
    });
    const catalog: SourceCatalog = {
      schema_version: 1,
      origin: "bundled",
      entries: [
        entry("fin", ["finance"]),
        entry("swe", ["swe"]),
        entry("cons", ["consulting", "business"]),
      ],
    };
    expect(sourceFieldsFor("business")).toContain("finance");
    expect(sourceFieldsFor("other")).toEqual([]);
    expect(sourceFieldsFor("")).toEqual([]);
    const picked = suggestedEntries(catalog, sourceFieldsFor("business"));
    expect(picked.map((e) => e.id)).toEqual(["fin", "cons"]);
    const out = sourcesFromCatalogPicks(SOURCES, picked, "business");
    // Built-in defaults are replaced, the student's own source stays, business gets a watchlist.
    expect(out.map((s) => s.id)).toEqual(["mine", "fin", "cons", "company-watchlist"]);
    expect(out[1]).toMatchObject({ catalog_id: "fin", catalog_version: "1" });
    expect(sourcesFromCatalogPicks(SOURCES, picked, "cs").some((s) => s.kind === "ats_board")).toBe(
      false,
    );
  });

  it("never preselects keyword searches, which need an API key", () => {
    const search: CatalogEntry = {
      id: "adzuna-finance-intern",
      name: "search",
      description: "",
      fields: ["finance"],
      version: "1",
      template: { id: "adzuna-finance-intern", kind: "job_search", provider: "adzuna", query: "x", enabled: true },
    } as CatalogEntry;
    const catalog = { schema_version: 1, origin: "bundled", entries: [search] } as SourceCatalog;
    expect(suggestedEntries(catalog, ["finance"])).toEqual([]);
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

  it("stores the chosen job fields beside the sources", () => {
    const apply = { sources: [], fields: ["swe"], max_age_days: 14 } as unknown as ApplySettings;
    const out = withSourceChoice(apply, SOURCES, ["finance", "quant"]);
    expect(out.sources).toBe(SOURCES);
    expect(out.fields).toEqual(["finance", "quant"]);
    expect(out.max_age_days).toBe(14);
    expect(apply.fields).toEqual(["swe"]);
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
