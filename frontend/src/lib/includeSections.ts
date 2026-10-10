/**
 * Pure logic behind the "What to include" section list: which exclusion list a section
 * kind writes to, per-entry toggling, the collapsed-row summary, and the display order.
 */
import type { IncludeOptions, ResumeOutline, ResumeOutlineSection } from "../api";
import { effectiveSectionOrder } from "./sectionOrder";

/** The `IncludeOptions` list that holds one section kind's excluded entries. */
type ExclusionKey = "exclude_entries" | "exclude_skill_groups" | "exclude_education";

export function exclusionKey(kind: string): ExclusionKey | null {
  if (kind === "experience" || kind === "project") return "exclude_entries";
  if (kind === "skills") return "exclude_skill_groups";
  if (kind === "education") return "exclude_education";
  return null;
}

/** Skill-group labels and education keys match case- and whitespace-insensitively,
 * like the server; entry ids match exactly. */
function norm(key: ExclusionKey, id: string): string {
  return key === "exclude_entries" ? id : id.trim().replace(/\s+/g, " ").toLowerCase();
}

function excludedSet(include: IncludeOptions, key: ExclusionKey): Set<string> {
  return new Set((include[key] ?? []).map((id) => norm(key, id)));
}

export function isEntryIncluded(include: IncludeOptions, kind: string, id: string): boolean {
  const key = exclusionKey(kind);
  return key === null || !excludedSet(include, key).has(norm(key, id));
}

/** The include patch that turns one entry on or off. */
export function toggleEntry(
  include: IncludeOptions,
  kind: string,
  id: string,
  on: boolean,
): Partial<IncludeOptions> {
  const key = exclusionKey(kind);
  if (key === null) return {};
  const current = include[key] ?? [];
  const target = norm(key, id);
  const without = current.filter((x) => norm(key, x) !== target);
  return { [key]: on ? without : [...without, id] };
}

export function isSectionIncluded(include: IncludeOptions, sectionId: string): boolean {
  return !include.exclude_sections.includes(sectionId);
}

/** The include patch that turns a whole section on or off. */
export function toggleSection(
  include: IncludeOptions,
  sectionId: string,
  on: boolean,
): Partial<IncludeOptions> {
  const without = include.exclude_sections.filter((id) => id !== sectionId);
  return { exclude_sections: on ? without : [...without, sectionId] };
}

/** Short text for a collapsed row, e.g. "4 of 6 included" or "3 of 4 groups". */
export function sectionSummary(include: IncludeOptions, section: ResumeOutlineSection): string {
  if (!isSectionIncluded(include, section.id)) return "Left out";
  const total = section.entries.length;
  if (total === 0) return "";
  const on = section.entries.filter((e) => isEntryIncluded(include, section.kind, e.id)).length;
  if (on === 0) return "Nothing included";
  if (on === total) return "All included";
  return `${on} of ${total}${section.kind === "skills" ? " groups" : " included"}`;
}

/** Sections in the order they will print: the per-run order under a generic template,
 * the resume's own order under a fixed one (where reordering has no effect). */
export function orderedSections(
  outline: ResumeOutline,
  include: IncludeOptions,
): ResumeOutlineSection[] {
  const byId = new Map(outline.sections.map((s) => [s.id, s]));
  const saved = outline.section_mode === "generic" ? include.section_order : null;
  return effectiveSectionOrder(saved, outline.sections)
    .map((id) => byId.get(id))
    .filter((s): s is ResumeOutlineSection => Boolean(s));
}
