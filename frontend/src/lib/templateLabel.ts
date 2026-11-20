/** Names for a saved template, worked out from the uploaded file. */

const LABEL_MAX = 80;

/** A default name from an upload's filename: its stem with separators as spaces. */
export function labelFromFilename(name: string): string {
  const stem = name.replace(/\.(docx|doc|odt|rtf)$/i, "").trim() || "Untitled";
  return stem
    .replace(/[\s_]+/g, " ")
    .trim()
    .slice(0, LABEL_MAX);
}

/**
 * `base`, or `base 2`, `base 3`… when a saved template already uses that name. The
 * server compares names without regard to case, so this does too. A student who uploads
 * the same file twice gets a second template instead of a "choose another label" error.
 */
export function uniqueLabel(base: string, taken: string[]): string {
  const used = new Set(taken.map((label) => label.trim().toLowerCase()));
  const clean = base.trim() || "Untitled";
  if (!used.has(clean.toLowerCase())) return clean;
  for (let n = 2; ; n++) {
    const suffix = ` ${n}`;
    const candidate = clean.slice(0, LABEL_MAX - suffix.length).trimEnd() + suffix;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
}
