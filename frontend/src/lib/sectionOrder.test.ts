import { describe, expect, it } from "vitest";
import { educationFirst, effectiveSectionOrder, needsEducationFirst } from "./sectionOrder";

const s = (kind: string, id = kind) => ({ kind, id });

describe("sectionOrder", () => {
  it("detects an Education section below another section", () => {
    expect(needsEducationFirst([s("experience"), s("education")])).toBe(true);
    expect(needsEducationFirst([s("education"), s("experience")])).toBe(false);
    expect(needsEducationFirst([s("experience"), s("skills")])).toBe(false);
    expect(needsEducationFirst([])).toBe(false);
  });

  it("moves every Education section up and keeps the rest in order", () => {
    const out = educationFirst([
      s("experience", "work"),
      s("education", "grad"),
      s("project"),
      s("education", "undergrad"),
    ]);
    expect(out.map((x) => x.id)).toEqual(["grad", "undergrad", "work", "project"]);
  });
});

describe("effectiveSectionOrder", () => {
  const sections = [{ id: "edu" }, { id: "work" }, { id: "skills" }];

  it("keeps the resume's own order when nothing is saved", () => {
    expect(effectiveSectionOrder(null, sections)).toEqual(["edu", "work", "skills"]);
  });

  it("honours a full saved order", () => {
    expect(effectiveSectionOrder(["skills", "edu", "work"], sections)).toEqual([
      "skills",
      "edu",
      "work",
    ]);
  });

  it("drops ids that no longer exist on the resume", () => {
    expect(effectiveSectionOrder(["skills", "gone", "edu"], sections)).toEqual([
      "skills",
      "edu",
      "work",
    ]);
  });

  it("appends a section not named in the saved order, in its resume-order position", () => {
    expect(effectiveSectionOrder(["skills"], sections)).toEqual(["skills", "edu", "work"]);
  });

  it("returns the resume's own order for an empty saved order", () => {
    expect(effectiveSectionOrder([], sections)).toEqual(["edu", "work", "skills"]);
  });
});
