import { describe, expect, it } from "vitest";
import type { CoverLetterField, CoverLetterSettings } from "../api";
import {
  coverSummary,
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

  it("summarises the defaults and the changes", () => {
    expect(coverSummary(base, fields)).toBe("Letterhead matches your resume");
    const changed: CoverLetterSettings = {
      ...base,
      letterhead: "custom",
      letterhead_fields: ["email"],
      blocks: { ...base.blocks, subject: true, date: false },
    };
    expect(coverSummary(changed, fields)).toBe(
      "Letterhead: Email · with a subject line · no date",
    );
  });
});
