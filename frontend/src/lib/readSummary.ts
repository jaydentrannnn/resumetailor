/** What the importer read from an uploaded resume, in a student's words. */
import { countLabel as plural } from "./countLabel";

type ReadSection = {
  key: string;
  heading_text: string;
  entry_count: number;
  bullet_count: number;
};

/** What one section's entries are called ("2 jobs", "1 school", "3 groups"). */
function entries(key: string, n: number): string {
  if (key === "experience") return plural(n, "job", "jobs");
  if (key === "projects") return plural(n, "project", "projects");
  if (key === "education") return plural(n, "school", "schools");
  if (key === "skills") return plural(n, "group", "groups");
  return plural(n, "entry", "entries");
}

/**
 * One line per section the importer found: the heading as the student wrote it, and how
 * much was read under it. This replaces the analyzer's own report (keys, paragraph
 * numbers, confidence) on the first-run upload, where the only question is "did it read
 * my resume?".
 */
export function readSummary(sections: ReadSection[]): { title: string; detail: string }[] {
  return sections.map((section) => ({
    title: section.heading_text.trim() || section.key,
    detail: [
      entries(section.key, section.entry_count),
      section.bullet_count > 0 ? plural(section.bullet_count, "bullet", "bullets") : "",
    ]
      .filter(Boolean)
      .join(", "),
  }));
}

/** How many entries a resume holds across all its sections. */
export function entryCount(
  resume: { sections: { entries: unknown[] }[] } | null | undefined,
): number {
  return resume?.sections.reduce((sum, section) => sum + section.entries.length, 0) ?? 0;
}

/**
 * What a saved resume holds, as a sentence fragment: "2 jobs, 2 projects and 8 bullets".
 * Jobs and projects are what a student recognises; skills groups and schools are left
 * out so the count matches what they would count on their own page.
 */
export function resumeTotals(
  resume: { sections: { kind: string; entries: object[] }[] } | null | undefined,
): string {
  const sections = resume?.sections ?? [];
  const count = (kind: string) =>
    sections.filter((s) => s.kind === kind).reduce((sum, s) => sum + s.entries.length, 0);
  // Skills groups and plain list items have no bullets of their own.
  const bulletsOf = (entry: object) => {
    const bullets = (entry as { bullets?: unknown }).bullets;
    return Array.isArray(bullets) ? bullets.length : 0;
  };
  const bullets = sections.reduce(
    (sum, s) => sum + s.entries.reduce((n: number, entry) => n + bulletsOf(entry), 0),
    0,
  );
  const parts = [
    count("experience") ? plural(count("experience"), "job", "jobs") : "",
    count("project") ? plural(count("project"), "project", "projects") : "",
    bullets ? plural(bullets, "bullet", "bullets") : "",
  ].filter(Boolean);
  if (parts.length === 0) return "";
  return parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
}
