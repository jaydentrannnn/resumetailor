import { useState } from "react";
import {
  inspectSource,
  type SourceCatalog,
  type SourceConfig,
  type SourceField,
  type SourceInspection,
} from "../../api";
import { Button, Modal, Tabs } from "../../components/ui";
import { describe } from "../../lib/errors";
import {
  catalogAdded,
  FIELD_LABELS,
  newJobSearchSource,
  newReadmeSource,
  SOURCE_FIELDS,
  sourceFromCatalog,
  splitPhrases,
} from "../../lib/sources";
import { newWatchlistSource } from "../../lib/watchlist";
import { CategoryPicker, JobSearchEditor, WatchlistEditor } from "./SourceEditors";
import { SourceTest } from "./SourceTest";

export type AddSourceTab = "catalog" | "readme" | "search" | "watchlist";

const TABS: { id: AddSourceTab; label: string }[] = [
  { id: "catalog", label: "Catalog" },
  { id: "readme", label: "README URL" },
  { id: "search", label: "Keyword search" },
  { id: "watchlist", label: "Company watchlist" },
];

const FORMAT_LABELS: Record<NonNullable<SourceInspection["kind"]>, string> = {
  simplify_html: "HTML job table (Simplify style)",
  pipe_table: "Markdown job table",
  company_link_table: "Per-company role tables",
};

/**
 * Add a job source four ways: from the curated catalog, by pasting a GitHub README job
 * list, as a keyword search (Adzuna / USAJobs), or as a company watchlist. Nothing is
 * added until the tab's Add button; the caller appends the source and saves.
 */
export function AddSourceDialog({
  sources,
  catalog,
  catalogError,
  onAdd,
  onClose,
  initialTab = "catalog",
}: {
  sources: SourceConfig[];
  catalog: SourceCatalog | null;
  catalogError: string;
  onAdd: (source: SourceConfig) => void;
  onClose: () => void;
  initialTab?: AddSourceTab;
}) {
  const [tab, setTab] = useState<AddSourceTab>(initialTab);
  const addAndClose = (source: SourceConfig) => {
    onAdd(source);
    onClose();
  };
  return (
    <Modal title="Add a job source" onClose={onClose} wide>
      <div className="mt-4 space-y-4">
        <Tabs
          label="How to add a source"
          items={TABS}
          value={tab}
          onChange={(id) => setTab(id as AddSourceTab)}
        />
        <div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)?.label}>
          {tab === "catalog" && (
            <CatalogTab
              sources={sources}
              catalog={catalog}
              catalogError={catalogError}
              onAdd={onAdd}
            />
          )}
          {tab === "readme" && <ReadmeTab sources={sources} onAdd={addAndClose} />}
          {tab === "search" && <SearchTab sources={sources} onAdd={addAndClose} />}
          {tab === "watchlist" && <WatchlistTab sources={sources} onAdd={addAndClose} />}
        </div>
      </div>
    </Modal>
  );
}

function CatalogTab({
  sources,
  catalog,
  catalogError,
  onAdd,
}: {
  sources: SourceConfig[];
  catalog: SourceCatalog | null;
  catalogError: string;
  onAdd: (source: SourceConfig) => void;
}) {
  const [fields, setFields] = useState<SourceField[]>([]);
  const [search, setSearch] = useState("");
  if (!catalog)
    return catalogError ? (
      <p role="alert" className="text-sm text-danger">
        Could not load the catalog: {catalogError}
      </p>
    ) : (
      <p role="status" className="text-sm text-ink-muted">
        Loading the catalog…
      </p>
    );
  const offered = SOURCE_FIELDS.filter((f) => catalog.entries.some((e) => e.fields.includes(f)));
  const needle = search.trim().toLowerCase();
  const shown = catalog.entries.filter(
    (entry) =>
      (fields.length === 0 || entry.fields.some((f) => fields.includes(f))) &&
      (!needle || `${entry.name} ${entry.description}`.toLowerCase().includes(needle)),
  );
  return (
    <div className="space-y-3 text-sm">
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
              className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-muted hover:border-accent"}`}
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
        <ul className="space-y-2">
          {shown.map((entry) => {
            const added = catalogAdded(entry, sources);
            return (
              <li
                key={entry.id}
                className="flex flex-wrap items-start gap-3 rounded-lg border border-line p-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{entry.name}</p>
                  <p className="text-xs text-ink-muted">{entry.description}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {entry.fields.map((field) => (
                      <span
                        key={field}
                        className="rounded-full bg-paper px-2 py-0.5 text-micro text-ink-muted"
                      >
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
    </div>
  );
}

function NameField({ value, onChange }: { value: string; onChange: (name: string) => void }) {
  return (
    <label className="block text-xs">
      <span className="font-medium">Name</span>
      <input
        className="field mt-1 w-full text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function ReadmeTab({
  sources,
  onAdd,
}: {
  sources: SourceConfig[];
  onAdd: (source: SourceConfig) => void;
}) {
  const [url, setUrl] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [inspection, setInspection] = useState<SourceInspection | null>(null);
  const [draft, setDraft] = useState<SourceConfig | null>(null);

  async function check() {
    setChecking(true);
    setError("");
    setInspection(null);
    setDraft(null);
    try {
      const found = await inspectSource(url.trim());
      setInspection(found);
      if (found.kind) setDraft(newReadmeSource(sources, url, found.kind, "", []));
    } catch (reason) {
      setError(describe(reason).detail);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="space-y-3 text-sm">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) void check();
        }}
      >
        <input
          aria-label="README link"
          className="field min-w-0 flex-1 text-sm"
          placeholder="https://github.com/owner/repo"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Button type="submit" size="sm" loading={checking} disabled={!url.trim()}>
          Check
        </Button>
      </form>
      <p className="text-xs text-ink-muted">
        Paste a GitHub job-list repository or its README link. It is read once to find its format
        and categories.
      </p>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      {inspection && !inspection.kind && (
        <p role="alert" className="rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">
          No job table found on that page. Check that it's the README of a job list.
        </p>
      )}
      {inspection?.kind && draft && (
        <div className="space-y-3 rounded-lg border border-line p-3">
          <p className="text-xs" aria-live="polite">
            <span className="font-medium">Format:</span> {FORMAT_LABELS[inspection.kind]} ·{" "}
            {inspection.row_count} posting{inspection.row_count === 1 ? "" : "s"}
          </p>
          <NameField value={draft.name ?? ""} onChange={(name) => setDraft({ ...draft, name })} />
          <CategoryPicker
            source={draft}
            initialSections={inspection.sections}
            onChange={setDraft}
          />
          <div className="flex flex-wrap items-start justify-between gap-2">
            <SourceTest source={draft} />
            <Button
              variant="primary"
              size="sm"
              onClick={() =>
                onAdd(
                  newReadmeSource(
                    sources,
                    draft.url,
                    inspection.kind!,
                    draft.name ?? "",
                    draft.categories,
                  ),
                )
              }
            >
              Add source
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function SearchTab({
  sources,
  onAdd,
}: {
  sources: SourceConfig[];
  onAdd: (source: SourceConfig) => void;
}) {
  const [draft, setDraft] = useState(() => newJobSearchSource(sources));
  const ready = splitPhrases(draft.query ?? "").length > 0;
  return (
    <div className="space-y-3 text-sm">
      <NameField value={draft.name ?? ""} onChange={(name) => setDraft({ ...draft, name })} />
      <JobSearchEditor source={draft} onChange={setDraft} />
      <div className="flex flex-wrap items-start justify-between gap-2">
        <SourceTest source={draft} disabled={!ready} />
        <Button
          variant="primary"
          size="sm"
          disabled={!ready}
          title={ready ? undefined : "Add at least one search phrase first"}
          onClick={() => onAdd(draft)}
        >
          Add search
        </Button>
      </div>
    </div>
  );
}

function WatchlistTab({
  sources,
  onAdd,
}: {
  sources: SourceConfig[];
  onAdd: (source: SourceConfig) => void;
}) {
  const [draft, setDraft] = useState<SourceConfig>(() => {
    const count = sources.filter((s) => s.kind === "ats_board").length;
    return {
      ...newWatchlistSource(undefined, sources),
      name: count ? `Company watchlist ${count + 1}` : "Company watchlist",
    };
  });
  return (
    <div className="space-y-3 text-sm">
      <NameField value={draft.name ?? ""} onChange={(name) => setDraft({ ...draft, name })} />
      <WatchlistEditor source={draft} onChange={setDraft} />
      <div className="flex justify-end">
        <Button variant="primary" size="sm" onClick={() => onAdd(draft)}>
          Add watchlist
        </Button>
      </div>
    </div>
  );
}
