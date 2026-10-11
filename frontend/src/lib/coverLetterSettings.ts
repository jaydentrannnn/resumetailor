import type { CoverBlockName, CoverLetterField, CoverLetterSettings } from "../api";

/** The optional letter blocks, in the order they print. The body always prints. */
export const COVER_BLOCKS: { id: CoverBlockName; label: string; help: string }[] = [
  { id: "date", label: "Date", help: "Today's date, above the recipient." },
  { id: "recipient", label: "Recipient", help: "The company and its location." },
  { id: "subject", label: "Subject line", help: "A line naming the role, before the greeting." },
  { id: "salutation", label: "Greeting", help: "“Dear Hiring Manager,” or the contact's name." },
  { id: "closing", label: "Sign-off", help: "The word before your name." },
  { id: "signature", label: "Signature", help: "Your name under the sign-off." },
];

/** `settings` with letterhead line `id` shown or hidden (switches to a custom letterhead,
 * seeded from every line, the first time a line is changed). */
export function withLetterheadField(
  settings: CoverLetterSettings,
  fields: CoverLetterField[],
  id: string,
  on: boolean,
): CoverLetterSettings {
  const current =
    settings.letterhead === "custom"
      ? settings.letterhead_fields
      : fields.filter((f) => f.has_value).map((f) => f.id);
  const next = on ? [...current.filter((x) => x !== id), id] : current.filter((x) => x !== id);
  const order = fields.map((f) => f.id);
  next.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return { ...settings, letterhead: "custom", letterhead_fields: next };
}

/** Whether letterhead line `id` prints under `settings`. */
export function letterheadShows(settings: CoverLetterSettings, field: CoverLetterField): boolean {
  return settings.letterhead === "same_as_resume"
    ? field.has_value
    : settings.letterhead_fields.includes(field.id);
}

/** The subject line as it would read for an example posting. */
export function subjectExample(format: string): string {
  return format
    .replaceAll("{job_title}", "Data Analyst")
    .replaceAll("{company}", "Example Company")
    .trim();
}

/** A part of the letter, in print order. `block` is its on/off switch (the body has
 * none); `expands` marks a part with options to show beneath it. */
export type LetterPart = {
  id: "letterhead" | CoverBlockName | "body";
  label: string;
  block?: CoverBlockName;
  expands: boolean;
};

const blockPart = (id: CoverBlockName): LetterPart => ({
  id,
  label: COVER_BLOCKS.find((b) => b.id === id)?.label ?? id,
  block: id,
  expands: id === "subject" || id === "closing",
});

export const LETTER_PARTS: LetterPart[] = [
  { id: "letterhead", label: "Letterhead", expands: true },
  ...(["date", "recipient", "subject", "salutation"] as const).map(blockPart),
  { id: "body", label: "Body", expands: false },
  ...(["closing", "signature"] as const).map(blockPart),
];

/** What a part prints, shown under its name (the only text a collapsed part shows). */
export function partSummary(
  part: LetterPart,
  settings: CoverLetterSettings,
  fields: CoverLetterField[],
): string {
  if (part.id === "letterhead") {
    if (settings.letterhead === "same_as_resume") return "Same as your resume";
    const shown = fields.filter((f) => settings.letterhead_fields.includes(f.id));
    return ["Name", ...shown.map((f) => f.label)].join(", ");
  }
  if (part.id === "subject") return `“${subjectExample(settings.subject_format)}”`;
  if (part.id === "closing") return settings.closing_text || "Sincerely,";
  if (part.id === "body") return "Your paragraphs, written for each job. Always prints.";
  return COVER_BLOCKS.find((b) => b.id === part.id)?.help ?? "";
}
