import { describe, expect, it } from "vitest";
import { completenessErrors, type MasterResume } from "./resumeEdit";

const resume = (bulletText: string): MasterResume => ({
  contact: { name: "Ada", email: "ada@example.com" },
  sections: [
    {
      id: "experience",
      title: "Experience",
      kind: "experience",
      entries: [
        {
          id: "acme",
          company: "Acme",
          title: "Engineer",
          start: "2024-01",
          end: "Present",
          bullets: [{ id: "acme_b1", text: bulletText, tags: [] }],
        },
      ],
    },
    {
      id: "projects",
      title: "Projects",
      kind: "project",
      entries: [{ id: "p", name: "Parser", bullets: [{ id: "p_b1", text: bulletText, tags: [] }] }],
    },
  ],
});

describe("completenessErrors", () => {
  it("accepts bullets with no Extra skills: their skills are computed", () => {
    expect(completenessErrors(resume("Built a parser in Python"))).toEqual([]);
  });

  it("still names an empty bullet", () => {
    expect(completenessErrors(resume("  "))).toEqual([
      "Acme — bullet 1 (acme_b1): text is empty",
      "Parser — bullet 1 (p_b1): text is empty",
    ]);
  });
});
