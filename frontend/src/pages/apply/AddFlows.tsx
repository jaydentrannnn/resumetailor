import { useState } from "react";
import {
  inspectSource,
  resolveBoard,
  saveSecret,
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
  PROVIDER_KEYS,
  PROVIDER_LABELS,
  SOURCE_FIELDS,
  sourceDisplayName,
  sourceFromCatalog,
  type SearchProvider,
} from "../../lib/sources";

/**
 * The dialogs around the source panel: the catalog (with a paste-a-link field) for job
 * lists, the chooser for which watchlist a pasted careers link joins, and Connect for a
 * search engine's keys. Adding a source itself happens in `SourcePanel`.
 */

/** An inspection that recognised a README format. */
export type KnownInspection = SourceInspection & { kind: NonNullable<SourceInspection["kind"]> };

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
    <Modal title="Add a job list" onClose={onClose} wide>
      <div className="mt-4 space-y-3 text-sm">
        <PasteLinkField sources={sources} onReadme={onReadme} onBoard={onBoard} />
        <h3 className="pt-1 text-sm font-semibold">Or pick from the catalog</h3>
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

/**
 * "Paste a link to any GitHub job list": a README is read first (its format is detected),
 * then the link is tried as a company careers page. Whichever it is, the matching add
 * panel opens prefilled.
 */
export function PasteLinkField({
  sources,
  onReadme,
  onBoard,
}: {
  sources: SourceConfig[];
  onReadme: (url: string, inspection: KnownInspection) => void;
  onBoard: (board: ResolvedBoard) => void;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    const link = url.trim();
    if (!link) return;
    const same = (a: string) => a.replace(/\/+$/, "") === link.replace(/\/+$/, "");
    const dup = sources.find((s) => s.url && same(s.url));
    if (dup) {
      setError(`Already in your sources as ${sourceDisplayName(dup)}.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      let inspection = null;
      try {
        inspection = await inspectSource(link);
      } catch {
        /* not a README we can read; try it as a careers page */
      }
      if (inspection?.kind) {
        onReadme(link, inspection as KnownInspection);
        return;
      }
      try {
        onBoard(await resolveBoard({ url: link }));
      } catch (reason) {
        const detail = describe(reason)
          .detail.replace(/\s*For more information check:.*$/s, "")
          .replace(/^Could not read the careers page:\s*/, "");
        setError(`That link is not a job list or a careers page we can read (${detail}).`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      aria-label="Paste a link"
      className="space-y-2 rounded-lg border border-line bg-paper p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label htmlFor="sources-paste-link" className="text-sm font-medium">
        Paste a link to any job list
      </label>
      <p className="text-xs text-ink-muted">
        A GitHub repo or README with a table of postings. A company careers page works too.
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          id="sources-paste-link"
          className="field min-w-0 flex-1 text-sm"
          placeholder="https://github.com/owner/repo"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Button type="submit" size="sm" variant="secondary" loading={busy} disabled={!url.trim()}>
          Add
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </form>
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
