import { describe, expect, it } from "vitest";
import type { IncludeOptions, ResumeOutline, ResumeOutlineSection } from "../api";
import { DEFAULT_INCLUDE } from "../state/runDefaults";
import {
  isEntryIncluded,
  orderedSections,
  sectionSummary,
  toggleEntry,
  toggleSection,
} from "./includeSections";

const work: ResumeOutlineSection = {
  id: "work",
  title: "Work",
  kind: "experience",
  entries: [
    { id: "a", label: "A", bullets: 3 },
    { id: "b", label: "B", bullets: 2 },
  ],
};
const skills: ResumeOutlineSection = {
  id: "skills",
  title: "Skills",
  kind: "skills",
  entries: [
    { id: "Languages", label: "Languages", bullets: 0, detail: "Python, Go" },
    { id: "Tools", label: "Tools", bullets: 0, detail: "Git" },
  ],
};
const edu: ResumeOutlineSection = {
  id: "edu",
  title: "Education",
  kind: "education",
  entries: [{ id: "State U|BS", label: "State U — BS", bullets: 0 }],
};

function inc(patch: Partial<IncludeOptions> = {}): IncludeOptions {
  return { ...DEFAULT_INCLUDE, ...patch };
}

describe("toggleEntry", () => {
  it("writes each kind to its own exclusion list", () => {
    expect(toggleEntry(inc(), "experience", "a", false)).toEqual({ exclude_entries: ["a"] });
    expect(toggleEntry(inc(), "skills", "Tools", false)).toEqual({
      exclude_skill_groups: ["Tools"],
    });
    expect(toggleEntry(inc(), "education", "State U|BS", false)).toEqual({
      exclude_education: ["State U|BS"],
    });
    expect(toggleEntry(inc(), "list", "x", false)).toEqual({});
  });

  it("re-including a skill group matches case-insensitively", () => {
    const include = inc({ exclude_skill_groups: ["tools "] });
    expect(isEntryIncluded(include, "skills", "Tools")).toBe(false);
    expect(toggleEntry(include, "skills", "Tools", true)).toEqual({ exclude_skill_groups: [] });
  });

  it("tolerates settings saved before the new lists existed", () => {
    const legacy = { ...DEFAULT_INCLUDE } as Partial<IncludeOptions>;
    delete legacy.exclude_skill_groups;
    expect(isEntryIncluded(legacy as IncludeOptions, "skills", "Tools")).toBe(true);
  });
});

describe("sectionSummary", () => {
  it("counts included entries", () => {
    expect(sectionSummary(inc(), work)).toBe("All included");
    expect(sectionSummary(inc({ exclude_entries: ["a"] }), work)).toBe("1 of 2 included");
    expect(sectionSummary(inc({ exclude_entries: ["a", "b"] }), work)).toBe("Nothing included");
    expect(sectionSummary(inc({ exclude_skill_groups: ["Tools"] }), skills)).toBe("1 of 2 groups");
    expect(sectionSummary(inc(toggleSection(inc(), "work", false)), work)).toBe("Left out");
  });
});

describe("orderedSections", () => {
  const outline = (mode: string) =>
    ({ sections: [work, edu, skills], section_mode: mode }) as unknown as ResumeOutline;

  it("follows the per-run order under a generic template", () => {
    const ids = orderedSections(outline("generic"), inc({ section_order: ["skills", "work"] }));
    expect(ids.map((s) => s.id)).toEqual(["skills", "work", "edu"]);
  });

  it("keeps the resume's order under a fixed template", () => {
    const ids = orderedSections(outline("fixed"), inc({ section_order: ["skills", "work"] }));
    expect(ids.map((s) => s.id)).toEqual(["work", "edu", "skills"]);
  });
});
