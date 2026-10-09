import { describe, expect, it } from "vitest";
import type { VocabularyEntry } from "../api";
import { filterVocabulary, isVerbShaped, termNames, vocabularyHas } from "./vocabularySearch";

const item = (value: string, builtin = true, hidden = false) => ({ value, builtin, hidden });
const ENTRIES: VocabularyEntry[] = [
  { kind: "term", name: "python", builtin: true, hidden: false, items: [item("py"), item("py3")] },
  { kind: "term", name: "postgresql", builtin: true, hidden: false, items: [item("pgx", false)] },
  { kind: "term", name: "quuxware", builtin: false, hidden: false, items: [] },
  { kind: "term", name: "excel", builtin: true, hidden: true, items: [item("pivot tables")] },
  {
    kind: "family",
    name: "build",
    builtin: true,
    hidden: false,
    items: [item("built"), item("py")],
  },
];

describe("filterVocabulary", () => {
  it("matches names and spellings, exact name first then exact spelling", () => {
    const names = filterVocabulary(ENTRIES, "py", "all").map((e) => e.name);
    expect(names).toEqual(["python", "build"]);
  });

  it("filters by kind, by your additions and by hidden entries", () => {
    expect(filterVocabulary(ENTRIES, "", "verbs").map((e) => e.name)).toEqual(["build"]);
    expect(filterVocabulary(ENTRIES, "", "yours").map((e) => e.name)).toEqual([
      "postgresql",
      "quuxware",
    ]);
    expect(filterVocabulary(ENTRIES, "", "hidden").map((e) => e.name)).toEqual(["excel"]);
  });

  it("is case- and whitespace-insensitive", () => {
    expect(filterVocabulary(ENTRIES, "  PIVOT ", "all").map((e) => e.name)).toEqual(["excel"]);
  });
});

describe("vocabulary helpers", () => {
  it("knows whether a word is already there", () => {
    expect(vocabularyHas(ENTRIES, "PGX")).toBe(true);
    expect(vocabularyHas(ENTRIES, "quuxware")).toBe(true);
    expect(vocabularyHas(ENTRIES, "rust")).toBe(false);
  });

  it("lists visible term names and recognises verb-shaped words", () => {
    expect(termNames(ENTRIES)).toEqual(["python", "postgresql", "quuxware"]);
    expect(isVerbShaped("Triaged")).toBe(true);
    expect(isVerbShaped("re-built")).toBe(false);
  });
});
