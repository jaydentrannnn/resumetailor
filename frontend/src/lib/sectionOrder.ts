/**
 * Section order helpers. For the starter templates: Business lists Education first, and
 * the rendered order follows the master resume's own section order, so installing it
 * offers to move the student's Education section(s) to the top.
 */
type SectionLike = { kind?: unknown };

/** True when some Education section comes after a non-Education one. */
export function needsEducationFirst(sections: readonly SectionLike[]): boolean {
  const firstOther = sections.findIndex((s) => s.kind !== "education");
  if (firstOther < 0) return false;
  return sections.slice(firstOther).some((s) => s.kind === "education");
}

/** Education sections first, everything else after; relative order is kept. */
export function educationFirst<T extends SectionLike>(sections: readonly T[]): T[] {
  return [
    ...sections.filter((s) => s.kind === "education"),
    ...sections.filter((s) => s.kind !== "education"),
  ];
}

/**
 * Merge a saved per-run section order against what the resume currently has: sections
 * named in `saved` come first (in that order, dropping ids that no longer exist), then
 * every other section keeps its resume-order relative position and is appended after.
 * Pure so it is testable without mounting React — mirrors `include._apply_section_order`
 * on the server, which resolves the same way at run time.
 */
export function effectiveSectionOrder(
  saved: string[] | null,
  sections: { id: string }[],
): string[] {
  const known = new Set(sections.map((s) => s.id));
  const namedValid = (saved ?? []).filter((id) => known.has(id));
  const namedSet = new Set(namedValid);
  const unnamed = sections.filter((s) => !namedSet.has(s.id)).map((s) => s.id);
  return [...namedValid, ...unnamed];
}
