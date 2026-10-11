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

/** One-line summary for the Template page card. */
export function coverSummary(settings: CoverLetterSettings, fields: CoverLetterField[]): string {
  const head =
    settings.letterhead === "same_as_resume"
      ? "Letterhead matches your resume"
      : `Letterhead: ${
          fields
            .filter((f) => settings.letterhead_fields.includes(f.id))
            .map((f) => f.label)
            .join(", ") || "name only"
        }`;
  const off = COVER_BLOCKS.filter((b) => b.id !== "subject" && !settings.blocks[b.id]).map(
    (b) => b.label.toLowerCase(),
  );
  const parts = [head];
  if (settings.blocks.subject) parts.push("with a subject line");
  if (off.length) parts.push(`no ${off.join(", ")}`);
  return parts.join(" · ");
}
