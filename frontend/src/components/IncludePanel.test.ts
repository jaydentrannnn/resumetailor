import { describe, expect, it } from "vitest";
import { effectiveSectionOrder } from "./IncludePanel";

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
