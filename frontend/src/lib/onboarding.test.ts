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
  applicationSummary,
  contentComplete,
  needsWelcome,
  openGaps,
  personalComplete,
  reviewResume,
  sourceFieldsForTarget,
  sourcesFromCatalogPicks,
  studyFieldForTarget,
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
  skipped_steps: [],
  resume_from_scratch: false,
  updated_at: "",
  ...over,
});

describe("onboarding helpers", () => {
  it("orders the steps", () => {
    expect(stepIndex("field")).toBe(0);
    expect(stepIndex("done")).toBe(ONBOARDING_STEPS.length - 1);
  });

  it("preselects job fields from the target field", () => {
    expect(sourceFieldsForTarget("software-data")).toEqual(["swe", "data"]);
    expect(sourceFieldsForTarget("finance-consulting")).toContain("finance");
    expect(sourceFieldsForTarget("general")).toEqual([]);
    expect(sourceFieldsForTarget("unknown")).toEqual([]);
    expect(sourceFieldsForTarget(null)).toEqual([]);
    expect(studyFieldForTarget("marketing")).toBe("business");
    expect(studyFieldForTarget("software-data")).toBe("cs");
    expect(studyFieldForTarget(null)).toBe("");
  });

  it("maps a target field to catalog entries and writes them as the sources", () => {
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
    const picked = suggestedEntries(catalog, sourceFieldsForTarget("finance-consulting"));
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
      template: {
        id: "adzuna-finance-intern",
        kind: "job_search",
        provider: "adzuna",
        query: "x",
        enabled: true,
      },
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
    expect(review.blocking).toEqual(["Your name is missing."]);
    expect(contentComplete(review)).toBe(false);
    resume.contact.name = "Ada Lovelace";
    expect(contentComplete(reviewResume(resume))).toBe(true);
    expect(contentComplete(reviewResume(null))).toBe(false);
    expect(reviewResume(null).entries).toBe(0);
  });

  it("requires names, an email and a phone, falling back to the resume contact", () => {
    const draft = { first_name: "Ada", last_name: "L", email: "", phone: "" };
    expect(personalComplete(draft, {})).toBe(false);
    expect(personalComplete(draft, {}, { email: "a@b.co", phone: "555 0100" })).toBe(true);
    // The starter resume's placeholder email does not count.
    expect(personalComplete(draft, {}, { email: "you@example.com", phone: "1" })).toBe(false);
    const typed = { ...draft, email: "a@b.co", phone: "5550100" };
    expect(personalComplete(typed, {})).toBe(true);
    expect(personalComplete(typed, { email: "bad" })).toBe(false);
    expect(personalComplete(null, {})).toBe(false);
    // A blank name the server fills from the resume header counts.
    const unnamed = { ...typed, first_name: "" };
    expect(personalComplete(unnamed, {})).toBe(false);
    expect(personalComplete(unnamed, {}, null, { first_name: "Ada" })).toBe(true);
  });

  it("lists the form questions still unanswered", () => {
    const draft = { city: "Irvine", state: " ", graduation_date: null, consent: false };
    expect(openGaps(["city", "state", "graduation_date", "consent"], draft)).toEqual([
      "state",
      "graduation_date",
    ]);
    expect(openGaps(["city"], null)).toEqual(["city"]);
  });

  it("echoes only filled application answers, with option labels", () => {
    const rows = applicationSummary(
      { visa_status: "f1", city: "", requires_sponsorship_now: true, gpa_display: "3.9" },
      [
        { fields: ["visa_status", "city"] },
        { fields: ["requires_sponsorship_now", "gpa_display"] },
      ],
      { visa_status: [["f1", "F-1 student"]] },
      (key) => key.toUpperCase(),
    );
    expect(rows).toEqual([
      { label: "VISA_STATUS", value: "F-1 student" },
      { label: "REQUIRES_SPONSORSHIP_NOW", value: "Yes" },
      { label: "GPA_DISPLAY", value: "3.9" },
    ]);
  });

  it("stores the chosen job fields beside the sources", () => {
    const apply = { sources: [], fields: ["swe"], max_age_days: 14 } as unknown as ApplySettings;
    const out = withSourceChoice(apply, SOURCES, ["finance", "quant"]);
    expect(out.sources).toBe(SOURCES);
    expect(out.fields).toEqual(["finance", "quant"]);
    expect(out.max_age_days).toBe(14);
    expect(apply.fields).toEqual(["swe"]);
  });

  it("keeps an unfinished profile on the wizard, Settings included", () => {
    expect(needsWelcome(state(), "/")).toBe(true);
    expect(needsWelcome(state(), "/settings")).toBe(true);
    expect(needsWelcome(state(), "/profile/resume")).toBe(true);
    expect(needsWelcome(state(), "/welcome")).toBe(false);
    expect(needsWelcome(state({ skipped: true }), "/")).toBe(false);
    expect(needsWelcome(state({ completed: true }), "/")).toBe(false);
    expect(needsWelcome(null, "/")).toBe(false);
  });
});
