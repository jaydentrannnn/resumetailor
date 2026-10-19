import { describe, expect, it } from "vitest";
import { entryMatches, sectionMatches } from "./entryFilter";
import type { Section } from "./resumeEdit";

const section = {
  id: "exp",
  title: "Experience",
  kind: "experience",
  entries: [
    {
      id: "acme",
      company: "Acme",
      title: "Engineer",
      bullets: [{ id: "b1", text: "Built a Kafka pipeline", tags: ["python"] }],
    },
  ],
} as unknown as Section;

describe("entry filter", () => {
  it("matches every word across the entry and its section title", () => {
    const entry = section.entries[0];
    expect(entryMatches(section, entry, "")).toBe(true);
    expect(entryMatches(section, entry, "kafka acme")).toBe(true);
    expect(entryMatches(section, entry, "experience engineer")).toBe(true);
    expect(entryMatches(section, entry, "kafka rust")).toBe(false);
  });

  it("ignores ids and tags", () => {
    expect(entryMatches(section, section.entries[0], "python")).toBe(false);
    expect(entryMatches(section, section.entries[0], "b1")).toBe(false);
    expect(sectionMatches(section, "pipeline")).toBe(true);
    expect(sectionMatches(section, "nothing")).toBe(false);
  });
});
