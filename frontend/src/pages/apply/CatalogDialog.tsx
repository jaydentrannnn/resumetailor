import { useState } from "react";
import type {
  ResolvedBoard,
  SourceCatalog,
  SourceConfig,
  SourceField,
  SourceLevel,
  SourceTrack,
} from "../../api";
import { Button, Modal } from "../../components/ui";
import {
  catalogAdded,
  entriesForFilters,
  FIELD_LABELS,
  LEVEL_LABELS,
  SOURCE_FIELDS,
  SOURCE_LEVELS,
  SOURCE_TRACKS,
  sourceFromCatalog,
  TRACK_LABELS,
} from "../../lib/sources";
import { PasteLinkField, type KnownInspection } from "./AddFlows";
import { FilterChips } from "./FilterChips";
/** "+ Add from catalog": the curated lists, prefiltered to ``fields`` (the user's fields). */
export function CatalogDialog({
  sources,
  catalog,
  catalogError,
  fields: initialFields,
  onAdd,
  onReadme,
  onBoard,
  onClose,
}: {
  sources: SourceConfig[];
  catalog: SourceCatalog | null;
  catalogError: string;
  fields: SourceField[];
  onAdd: (source: SourceConfig) => void;
  onReadme: (url: string, inspection: KnownInspection) => void;
  onBoard: (board: ResolvedBoard) => void;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<SourceField[]>(initialFields);
  const [search, setSearch] = useState("");
  return (
    <Modal title="Add a job list" onClose={onClose} placement="right">
      <div className="mt-4 space-y-3 text-sm">
        <PasteLinkField sources={sources} onReadme={onReadme} onBoard={onBoard} />
        <h3 className="border-t border-line pt-4 text-sm font-semibold">
          Or pick from the catalog
        </h3>
        {!catalog ? (
          catalogError ? (
            <p role="alert" className="text-sm text-danger">
              Could not load the catalog: {catalogError}
            </p>
          ) : (
            <p role="status" className="text-sm text-ink-muted">
              Loading the catalog…
            </p>
          )
        ) : (
          <CatalogList
            sources={sources}
            catalog={catalog}
            fields={fields}
            setFields={setFields}
            search={search}
            setSearch={setSearch}
            onAdd={onAdd}
          />
        )}
      </div>
    </Modal>
  );
}

function CatalogList({
  sources,
  catalog,
  fields,
  setFields,
  search,
  setSearch,
  onAdd,
}: {
  sources: SourceConfig[];
  catalog: SourceCatalog;
  fields: SourceField[];
  setFields: (next: SourceField[]) => void;
  search: string;
  setSearch: (next: string) => void;
  onAdd: (source: SourceConfig) => void;
}) {
  const [levels, setLevels] = useState<SourceLevel[]>([]);
  const [tracks, setTracks] = useState<SourceTrack[]>([]);
  const offered = SOURCE_FIELDS.filter((f) => catalog.entries.some((e) => e.fields.includes(f)));
  const offeredLevels = SOURCE_LEVELS.filter((l) => catalog.entries.some((e) => e.levels?.includes(l)));
  const offeredTracks = SOURCE_TRACKS.filter((t) => catalog.entries.some((e) => e.tracks?.includes(t)));
  const needle = search.trim().toLowerCase();
  const shown = entriesForFilters(catalog, { fields, levels, tracks }).filter(
    (entry) => !needle || `${entry.name} ${entry.description}`.toLowerCase().includes(needle),
  );
  return (
    <>
      <input
        type="search"
        aria-label="Search the catalog"
        placeholder="Search by name or description"
        className="field w-full text-sm"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <FilterChips
        label="Filter by field"
        options={offered}
        labels={FIELD_LABELS}
        selected={fields}
        onChange={setFields}
      />
      <FilterChips
        label="Filter by level"
        options={offeredLevels}
        labels={LEVEL_LABELS}
        selected={levels}
        onChange={setLevels}
      />
      <FilterChips
        label="Filter by focus"
        options={offeredTracks}
        labels={TRACK_LABELS}
        selected={tracks}
        onChange={setTracks}
      />
      {shown.length === 0 ? (
        <p className="text-ink-muted">No catalog source matches.</p>
      ) : (
        <ul className="divide-y divide-line">
          {shown.map((entry) => {
            const added = catalogAdded(entry, sources);
            return (
              <li key={entry.id} className="flex flex-wrap items-start gap-3 py-4">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{entry.name}</p>
                  <p className="text-xs text-ink-muted">{entry.description}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {[
                      ...entry.fields.map((f) => FIELD_LABELS[f] ?? f),
                      ...(entry.levels ?? []).map((l) => LEVEL_LABELS[l] ?? l),
                      ...(entry.tracks ?? []).map((t) => TRACK_LABELS[t] ?? t),
                    ].map((label) => (
                      <span key={label} className="text-xs text-ink-muted">
                        {label}
                      </span>
                    ))}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant={added ? "ghost" : "secondary"}
                  disabled={added}
                  aria-label={added ? `${entry.name} added` : `Add ${entry.name}`}
                  onClick={() => onAdd(sourceFromCatalog(entry, sources))}
                >
                  {added ? "✓ Added" : "Add"}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      {catalog.origin === "bundled" && (
        <p className="text-xs text-ink-muted">
          Showing the catalog shipped with the app (the online copy could not be reached).
        </p>
      )}
    </>
  );
}
