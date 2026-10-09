import type { VocabularyEntry } from "../api";

export type VocabularyFilter = "all" | "terms" | "verbs" | "yours" | "hidden";

export const VOCABULARY_FILTERS: { id: VocabularyFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "terms", label: "Terms" },
  { id: "verbs", label: "Verbs" },
  { id: "yours", label: "Yours" },
  { id: "hidden", label: "Hidden" },
];

function norm(value: string): string {
  return value.trim().toLowerCase();
}

function passesFilter(entry: VocabularyEntry, filter: VocabularyFilter): boolean {
  switch (filter) {
    case "terms":
      return entry.kind === "term";
    case "verbs":
      return entry.kind === "family";
    case "yours":
      return !entry.builtin || entry.items.some((i) => !i.builtin);
    case "hidden":
      return entry.hidden || entry.items.some((i) => i.hidden);
    default:
      return true;
  }
}

/** Entries whose name or any spelling/verb contains `query`, best matches first:
 * an exact name, then an exact spelling, then everything else in list order. */
export function filterVocabulary(
  entries: VocabularyEntry[],
  query: string,
  filter: VocabularyFilter,
): VocabularyEntry[] {
  const q = norm(query);
  const hits = entries.filter(
    (e) =>
      passesFilter(e, filter) &&
      (!q || e.name.includes(q) || e.items.some((i) => i.value.includes(q))),
  );
  if (!q) return hits;
  const rank = (e: VocabularyEntry) =>
    e.name === q ? 0 : e.items.some((i) => i.value === q) ? 1 : 2;
  return hits
    .map((e, index) => ({ e, index }))
    .sort((a, b) => rank(a.e) - rank(b.e) || a.index - b.index)
    .map(({ e }) => e);
}

/** Whether `query` is already in the dictionary as a term, spelling or verb. */
export function vocabularyHas(entries: VocabularyEntry[], query: string): boolean {
  const q = norm(query);
  return entries.some(
    (e) => (e.kind === "term" && e.name === q) || e.items.some((i) => i.value === q),
  );
}

/** Names of every visible term, for the "another name for…" picker. */
export function termNames(entries: VocabularyEntry[]): string[] {
  return entries.filter((e) => e.kind === "term" && !e.hidden).map((e) => e.name);
}

/** Names of every verb family. */
export function familyNames(entries: VocabularyEntry[]): string[] {
  return entries.filter((e) => e.kind === "family").map((e) => e.name);
}

/** A single word of letters — the only shape an opening verb can take. */
export function isVerbShaped(value: string): boolean {
  return /^[a-z]+$/.test(norm(value));
}
