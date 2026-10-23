import { describe, expect, it } from "vitest";
import type { SkillGap } from "../api";
import { gapItems } from "./skillGaps";

const gap = (skill: string, jobs: number, companies: string[]): SkillGap => ({
  skill,
  canonical: skill.toLowerCase(),
  jobs,
  weight: jobs / 2,
  companies,
});

describe("gapItems", () => {
  it("names the companies and how many more asked", () => {
    const [item] = gapItems([gap("Kubernetes", 5, ["Acme", "Globex", "Initech"])]);
    expect(item).toEqual({
      label: "Kubernetes",
      count: 5,
      title: "5 postings: Acme, Globex, Initech and 2 more",
    });
    expect(gapItems([gap("Go", 1, ["Acme"])])[0].title).toBe("1 posting: Acme");
  });

  it("keeps the first few in the server's order", () => {
    const gaps = ["A", "B", "C"].map((skill) => gap(skill, 1, []));
    expect(gapItems(gaps, 2).map((item) => item.label)).toEqual(["A", "B"]);
    expect(gapItems(gaps)[0].title).toBe("1 posting");
  });
});
