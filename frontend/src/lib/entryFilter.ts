import type { Section } from "./resumeEdit";

const SKIP = new Set(["id", "_key", "tags", "kind"]);

function texts(value: unknown, out: string[]): string[] {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((item) => texts(item, out));
  else if (value && typeof value === "object")
    for (const [key, item] of Object.entries(value)) if (!SKIP.has(key)) texts(item, out);
  return out;
}

/**
 * Whether a resume entry shows under the editor's filter: every word of the query must
 * appear in the entry's own text (company, title, dates, bullets…) or its section title.
 */
export function entryMatches(section: Section, entry: unknown, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const haystack = [section.title, ...texts(entry, [])].join("\n").toLowerCase();
  return words.every((word) => haystack.includes(word));
}

/** Whether any entry of a section shows under the filter (a section with none is hidden). */
export function sectionMatches(section: Section, query: string): boolean {
  return (section.entries as unknown[]).some((entry) => entryMatches(section, entry, query));
}
