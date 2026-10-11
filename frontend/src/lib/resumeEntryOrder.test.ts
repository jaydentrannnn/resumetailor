import { describe, expect, it } from "vitest";
import cases from "../../../tests/fixtures/entry_order_cases.json";
import { entryDateKey, orderResumeEntries } from "./resumeEntryOrder";
import type { MasterResume } from "./resumeEdit";
import type { ResumeEntry } from "./resumeEntryEdit";

function expectedMonth(text: string): number {
  if (text === "Present") return 999999;
  if (!text) return 0;
  const [year, month] = text.split("-").map(Number);
  return year * 12 + month;
}

describe("shared chronological date cases", () => {
  it.each(cases)("$name", ({ entry, expected }) => {
    expect(entryDateKey(entry as ResumeEntry)).toEqual(expected.map(expectedMonth));
  });
});

it("sorts dated sections independently, preserves ties and identities, and leaves other order alone", () => {
  const entries = [
    { id: "old", company: "Old", title: "Engineer", start: "2020-01", end: "2021-01", bullets: [] },
    { id: "now", company: "Now", title: "Engineer", start: "2024-01", end: "Present", bullets: [] },
    { id: "tie", company: "Tie", title: "Engineer", start: "2024-01", end: "Present", bullets: [] },
    { id: "blank", company: "", title: "", start: "", end: "", bullets: [] },
  ];
  const resume: MasterResume = {
    contact: { name: "Test", email: "test@example.com" },
    tag_vocabulary: [],
    sections: [
      { id: "jobs", kind: "experience", title: "Jobs", entries },
      { id: "other", kind: "experience", title: "Other", entries: [entries[0]] },
      {
        id: "skills",
        kind: "skills",
        title: "Skills",
        entries: [
          { label: "Z", items: [] },
          { label: "A", items: [] },
        ],
      },
    ],
  };
  const result = orderResumeEntries(resume);
  expect(result.sections[0].entries).toEqual([entries[1], entries[2], entries[0], entries[3]]);
  expect(result.sections[0].entries[0]).toBe(entries[1]);
  expect(result.sections[1]).toBe(resume.sections[1]);
  expect(result.sections[2]).toBe(resume.sections[2]);
  expect(orderResumeEntries(result)).toBe(result);
  expect(resume.sections[0].entries).toBe(entries);
});
