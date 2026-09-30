import { useState } from "react";
import {
  saveSecret,
  type BoardConfig,
  type ResolvedBoard,
  type SourceCatalog,
  type SourceConfig,
  type SourceField,
  type SourceInspection,
} from "../../api";
import { Button, Modal } from "../../components/ui";
import { describe } from "../../lib/errors";
import {
  catalogAdded,
  FIELD_LABELS,
  newJobSearchSource,
  newReadmeSource,
  PROVIDER_KEYS,
  PROVIDER_LABELS,
  SOURCE_FIELDS,
  sourceDisplayName,
  sourceFromCatalog,
  splitPhrases,
  type SearchProvider,
} from "../../lib/sources";
import { newWatchlistSource } from "../../lib/watchlist";
import { CategoryPicker, JobSearchEditor, WatchlistEditor } from "./SourceEditors";
import { SourceTest } from "./SourceTest";

/**
 * The per-group "add" flows of the Sources tab: the catalog for job lists, a keyword
 * search per provider, a company watchlist, and the two flows the "paste a link" bar
 * opens (a README that was just inspected, a careers page that was just resolved). Each
 * is a dialog; nothing is added until its own Add button.
 */

/** An inspection that recognised a README format. */
export type KnownInspection = SourceInspection & { kind: NonNullable<SourceInspection["kind"]> };

const FORMAT_LABELS: Record<NonNullable<SourceInspection["kind"]>, string> = {
  simplify_html: "HTML job table (Simplify style)",
  pipe_table: "Markdown job table",
  company_link_table: "Per-company role tables",
};

export function NameField({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (name: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block text-xs">
      <span className="font-medium">Name</span>
      <input
        className="field mt-1 w-full text-sm"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

/** "+ Add from catalog": the curated lists, prefiltered to ``fields`` (the user's fields). */
export function CatalogDialog({
  sources,
  catalog,
  catalogError,
  fields: initialFields,
  onAdd,
  onClose,
}: {
  sources: SourceConfig[];
  catalog: SourceCatalog | null;
  catalogError: string;
  fields: SourceField[];
  onAdd: (source: SourceConfig) => void;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<SourceField[]>(initialFields);
  const [search, setSearch] = useState("");
  return (
    <Modal title="Add a job list from the catalog" onClose={onClose} wide>
      <div className="mt-4 space-y-3 text-sm">
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
    </>
  );
}

/** A pasted job-list link whose format was detected: name it, pick categories, test, add. */
export function ReadmeFlowDialog({
  sources,
  url,
  inspection,
  onAdd,
  onClose,
}: {
  sources: SourceConfig[];
  url: string;
  inspection: KnownInspection;
  onAdd: (source: SourceConfig) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<SourceConfig>(() =>
    newReadmeSource(sources, url, inspection.kind, "", []),
  );
  return (
    <Modal title="Add a job list" onClose={onClose} wide>
      <div className="mt-4 space-y-3 text-sm">
        <p className="text-xs" aria-live="polite">
          <span className="font-medium">Format:</span> {FORMAT_LABELS[inspection.kind]} ·{" "}
          {inspection.row_count} posting{inspection.row_count === 1 ? "" : "s"}
        </p>
        <NameField
          value={draft.name ?? ""}
          placeholder={sourceDisplayName(draft)}
          onChange={(name) => setDraft({ ...draft, name })}
        />
        <CategoryPicker source={draft} initialSections={inspection.sections} onChange={setDraft} />
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
                  inspection.kind,
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
    </Modal>
  );
}

/** "+ New <provider> search": phrases, location and filters; keys live in the Connect dialog. */
export function SearchFlowDialog({
  provider,
  sources,
  connected,
  onConnect,
  onAdd,
  onClose,
}: {
  provider: SearchProvider;
  sources: SourceConfig[];
  connected: boolean | null;
  onConnect: () => void;
  onAdd: (source: SourceConfig) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(() => newJobSearchSource(sources, { provider }));
  const ready = splitPhrases(draft.query ?? "").length > 0;
  return (
    <Modal title={`New ${PROVIDER_LABELS[provider]} search`} onClose={onClose} wide>
      <div className="mt-4 space-y-3 text-sm">
        <NameField
          value={draft.name ?? ""}
          placeholder={sourceDisplayName(draft)}
          onChange={(name) => setDraft({ ...draft, name })}
        />
        <JobSearchEditor
          source={draft}
          onChange={setDraft}
          connected={connected}
          onConnect={onConnect}
        />
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
    </Modal>
  );
}

/** "+ New watchlist" (empty, or with the company a pasted careers link resolved to). */
export function WatchlistFlowDialog({
  sources,
  board,
  onAdd,
  onClose,
}: {
  sources: SourceConfig[];
  board?: BoardConfig;
  onAdd: (source: SourceConfig) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<SourceConfig>(() => {
    const count = sources.filter((s) => s.kind === "ats_board").length;
    return {
      ...newWatchlistSource(undefined, sources),
      name: count ? `Company watchlist ${count + 1}` : "Company watchlist",
      boards: board ? [{ ats: board.ats, slug: board.slug, company: board.company }] : [],
    };
  });
  return (
    <Modal title="New company watchlist" onClose={onClose} wide>
      <div className="mt-4 space-y-3 text-sm">
        <NameField value={draft.name ?? ""} onChange={(name) => setDraft({ ...draft, name })} />
        <WatchlistEditor source={draft} onChange={setDraft} />
        <div className="flex justify-end">
          <Button variant="primary" size="sm" onClick={() => onAdd(draft)}>
            Add watchlist
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** A pasted careers link resolved to a company: add it to a watchlist you have, or start one. */
export function BoardTargetDialog({
  board,
  watchlists,
  onAddTo,
  onNew,
  onClose,
}: {
  board: ResolvedBoard;
  watchlists: SourceConfig[];
  onAddTo: (id: string) => void;
  onNew: () => void;
  onClose: () => void;
}) {
  const [target, setTarget] = useState(watchlists[0]?.id ?? "");
  return (
    <Modal title="Add this company" onClose={onClose}>
      <div className="mt-4 space-y-3 text-sm">
        <p>
          Found <strong>{board.company || board.slug}</strong> on {board.ats} · {board.jobs} open
          posting{board.jobs === 1 ? "" : "s"}.
        </p>
        <label className="block text-xs">
          <span className="font-medium">Add it to</span>
          <select
            className="field mt-1 w-full text-sm"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            {watchlists.map((w) => (
              <option key={w.id} value={w.id}>
                {sourceDisplayName(w)}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap justify-between gap-2">
          <Button variant="secondary" size="sm" onClick={onNew}>
            Start a new watchlist
          </Button>
          <Button variant="primary" size="sm" disabled={!target} onClick={() => onAddTo(target)}>
            Add company
          </Button>
        </div>
      </div>
    </Modal>
  );
}

const KEY_LINKS: Record<SearchProvider, string> = {
  adzuna: "https://developer.adzuna.com/signup",
  usajobs: "https://developer.usajobs.gov/apirequest/",
};

/**
 * Save a search engine's API keys once (OS keychain, through `/api/secrets`; values are
 * never read back). Every search on that engine then works.
 */
export function ConnectDialog({
  provider,
  savedKeys,
  onSaved,
  onClose,
}: {
  provider: SearchProvider;
  savedKeys: Set<string>;
  onSaved: () => void;
  onClose: () => void;
}) {
  const label = PROVIDER_LABELS[provider];
  const keys = PROVIDER_KEYS[provider];
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const complete = keys.every((k) => savedKeys.has(k.name) || values[k.name]?.trim());

  async function save() {
    setSaving(true);
    setError("");
    try {
      for (const key of keys) {
        const value = values[key.name]?.trim();
        if (value) await saveSecret(key.name, value);
      }
      onSaved();
      onClose();
    } catch (reason) {
      setError(describe(reason).detail);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Connect ${label}`} onClose={onClose}>
      <form
        className="mt-4 space-y-3 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          if (complete) void save();
        }}
      >
        <p className="text-xs text-ink-muted">
          Saved once in your system keychain and used by every {label} search.{" "}
          <a
            className="text-accent underline"
            href={KEY_LINKS[provider]}
            target="_blank"
            rel="noreferrer"
          >
            Get a free key
          </a>
        </p>
        {keys.map((key) => (
          <label key={key.name} className="block text-xs">
            <span className="font-medium">{key.label}</span>
            <input
              className="field mt-1 w-full text-sm"
              type={key.name.endsWith("EMAIL") ? "email" : "password"}
              autoComplete="off"
              placeholder={savedKeys.has(key.name) ? "Saved (leave blank to keep)" : ""}
              value={values[key.name] ?? ""}
              onChange={(e) => setValues((prev) => ({ ...prev, [key.name]: e.target.value }))}
            />
          </label>
        ))}
        {error && (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end">
          <Button type="submit" variant="primary" size="sm" loading={saving} disabled={!complete}>
            Save keys
          </Button>
        </div>
      </form>
    </Modal>
  );
}
