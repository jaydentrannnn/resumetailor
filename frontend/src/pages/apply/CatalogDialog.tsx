import { useState } from "react";
import type { ResolvedBoard, SourceCatalog, SourceConfig, SourceField } from "../../api";
import { Button, Modal } from "../../components/ui";
import { catalogAdded, FIELD_LABELS, SOURCE_FIELDS, sourceFromCatalog } from "../../lib/sources";
import { PasteLinkField, type KnownInspection } from "./AddFlows";
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
  const offered = SOURCE_FIELDS.filter((f) => catalog.entries.some((e) => e.fields.includes(f)));
  const needle = search.trim().toLowerCase();
  const shown = catalog.entries.filter(
    (entry) =>
      (fields.length === 0 || entry.fields.some((f) => fields.includes(f))) &&
      (!needle || `${entry.name} ${entry.description}`.toLowerCase().includes(needle)),
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
      <div role="group" aria-label="Filter by field" className="flex flex-wrap gap-1.5">
        {offered.map((field) => {
          const on = fields.includes(field);
          return (
            <button
              key={field}
              type="button"
              aria-pressed={on}
              className={`rounded-sm border px-2.5 py-0.5 text-xs ${on ? "border-selected-line bg-selected text-on-selected" : "border-line text-ink-muted hover:border-accent"}`}
              onClick={() => setFields(on ? fields.filter((f) => f !== field) : [...fields, field])}
            >
              {FIELD_LABELS[field]}
            </button>
          );
        })}
      </div>
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
                    {entry.fields.map((field) => (
                      <span key={field} className="text-xs text-ink-muted">
                        {FIELD_LABELS[field] ?? field}
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
