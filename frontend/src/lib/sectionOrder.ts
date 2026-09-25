/**
 * Section reordering for the starter templates. Business lists Education first, and
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
