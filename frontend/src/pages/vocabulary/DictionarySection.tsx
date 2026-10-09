import { useMemo, useState } from "react";
import { Segmented, Tile } from "../../components/ui";
import {
  VOCABULARY_FILTERS,
  type VocabularyFilter,
  filterVocabulary,
  vocabularyHas,
} from "../../lib/vocabularySearch";
import { useLibraryState } from "../../state/libraryState";
import { AddVocabulary } from "./AddVocabulary";
import { EntryRow } from "./EntryRow";

/** Search the whole dictionary; add what's missing; hide or remove entries. */
export function DictionarySection() {
  const { entries, loading, error } = useLibraryState();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<VocabularyFilter>("all");
  const shown = useMemo(() => filterVocabulary(entries, query, filter), [entries, query, filter]);
  const missing = query.trim() !== "" && !loading && !vocabularyHas(entries, query);

  return (
    <Tile
      title="Dictionary"
      description="Different spellings of the same skill, so a posting's “Postgres” matches your “PostgreSQL”, and the opening verbs used to keep bullets varied. Built-in entries can be hidden; your own can be removed. Changes apply to every profile."
    >
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search a skill, spelling or verb…"
        aria-label="Search the dictionary"
        className="field"
      />
      <Segmented
        className="mt-3"
        label="Show"
        items={VOCABULARY_FILTERS}
        value={filter}
        onChange={(id) => setFilter(id as VocabularyFilter)}
      />
      {error && (
        <p className="mt-3 rounded-sm bg-danger-soft px-3 py-2 text-xs text-danger">{error}</p>
      )}
      {missing && (
        <div className="mt-3">
          <AddVocabulary word={query} onAdded={() => setFilter("all")} />
        </div>
      )}
      <ul
        aria-label="Dictionary entries"
        className="mt-3 max-h-[60vh] overflow-y-auto rounded-sm border border-line px-3"
      >
        {shown.map((entry) => (
          <EntryRow key={`${entry.kind}:${entry.name}`} entry={entry} />
        ))}
        {shown.length === 0 && (
          <li className="py-6 text-center text-sm text-ink-muted">
            {loading ? "Loading…" : "Nothing matches."}
          </li>
        )}
      </ul>
    </Tile>
  );
}
