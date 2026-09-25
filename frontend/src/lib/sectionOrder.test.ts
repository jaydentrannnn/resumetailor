import { describe, expect, it } from "vitest";
import { educationFirst, needsEducationFirst } from "./sectionOrder";

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
