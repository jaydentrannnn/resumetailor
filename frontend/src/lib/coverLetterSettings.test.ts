import { describe, expect, it } from "vitest";
import type { CoverLetterField, CoverLetterSettings } from "../api";
import {
  LETTER_PARTS,
  partSummary,
  letterheadShows,
  subjectExample,
  withLetterheadField,
} from "./coverLetterSettings";

const fields: CoverLetterField[] = [
  { id: "location", label: "Location", has_value: true },
  { id: "email", label: "Email", has_value: true },
  { id: "github", label: "GitHub", has_value: false },
  { id: "custom:street_address", label: "Street address", has_value: true },
];

const base: CoverLetterSettings = {
  letterhead: "same_as_resume",
  letterhead_fields: [],
  blocks: {
    date: true,
    recipient: true,
    subject: false,
    salutation: true,
    closing: true,
    signature: true,
  },
  subject_format: "Application for {job_title}",
  closing_text: "Sincerely,",
};

describe("letterhead", () => {
  it("shows every line with a value when same as the resume", () => {
    expect(fields.map((f) => letterheadShows(base, f))).toEqual([true, true, false, true]);
  });

  it("unticking a line switches to a chosen set seeded from the shown lines", () => {
    const next = withLetterheadField(base, fields, "email", false);
    expect(next.letterhead).toBe("custom");
    expect(next.letterhead_fields).toEqual(["location", "custom:street_address"]);
  });

  it("keeps the chosen lines in letterhead order", () => {
    const custom = { ...base, letterhead: "custom" as const, letterhead_fields: ["email"] };
    const next = withLetterheadField(custom, fields, "location", true);
    expect(next.letterhead_fields).toEqual(["location", "email"]);
  });
});

describe("summaries", () => {
  it("fills the subject example", () => {
    expect(subjectExample("Re: {job_title} at {company}")).toBe(
      "Re: Data Analyst at Example Company",
    );
  });

  it("lists the parts in print order; only parts with options expand", () => {
    expect(LETTER_PARTS.map((p) => p.id)).toEqual([
      "letterhead",
      "date",
      "recipient",
      "subject",
      "salutation",
      "body",
      "closing",
      "signature",
    ]);
    expect(LETTER_PARTS.filter((p) => p.expands).map((p) => p.id)).toEqual([
      "letterhead",
      "subject",
      "closing",
    ]);
    expect(LETTER_PARTS.find((p) => p.id === "body")?.block).toBeUndefined();
  });

  it("summarises a collapsed part", () => {
    const part = (id: string) => LETTER_PARTS.find((p) => p.id === id)!;
    expect(partSummary(part("letterhead"), base, fields)).toBe("Same as your resume");
    const custom = { ...base, letterhead: "custom" as const, letterhead_fields: ["email"] };
    expect(partSummary(part("letterhead"), custom, fields)).toBe("Name, Email");
    expect(partSummary(part("letterhead"), { ...custom, letterhead_fields: [] }, fields)).toBe(
      "Name",
    );
    expect(partSummary(part("subject"), base, fields)).toBe("“Application for Data Analyst”");
    expect(partSummary(part("closing"), base, fields)).toBe("Sincerely,");
  });
});
