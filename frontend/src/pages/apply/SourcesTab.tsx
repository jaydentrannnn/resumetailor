import { useEffect, useState } from "react";
import {
  fetchSourceCatalog,
  type CatalogEntry,
  type SourceCatalog,
  type SourceConfig,
} from "../../api";
import { Button, EmptyState } from "../../components/ui";
import { describe } from "../../lib/errors";
import {
  applyCatalogUpdate,
  availableUpdate,
  catalogDiff,
  isReadmeKind,
  restoreDefaults,
  sourceDisplayName,
  sourceKindLabel,
  FIELD_LABELS,
} from "../../lib/sources";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import { AddSourceDialog } from "./AddSourceDialog";
import { CategoryPicker, JobSearchEditor, WatchlistEditor } from "./SourceEditors";
import { SourceTest } from "./SourceTest";

/**
 * The Apply page's Sources tab: every place the nightly run looks for jobs. Changes go
 * through `onChange` (the settings autosave); `saveError` shows a server validation error.
 */
export function SourcesTab({
  sources,
  onChange,
  saveError,
}: {
  sources: SourceConfig[];
  onChange: (next: SourceConfig[]) => void;
  saveError: string | null;
}) {
  const { confirm } = useConfirm();
  const toast = useToast();
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchSourceCatalog()
      .then((c) => live && setCatalog(c))
      .catch((reason) => live && setCatalogError(describe(reason).detail));
    return () => {
      live = false;
    };
  }, []);

  const update = (id: string, next: SourceConfig) =>
    onChange(sources.map((s) => (s.id === id ? next : s)));

  async function remove(source: SourceConfig) {
    const ok = await confirm({
      title: `Remove ${sourceDisplayName(source)}?`,
      message:
        "It will no longer be searched. Postings already found stay in your applications. You can add it back from the catalog.",
      confirmLabel: "Remove",
      tone: "danger",
    });
    if (ok) onChange(sources.filter((s) => s.id !== source.id));
  }

  async function restore() {
    if (!catalog) {
      toast.error("Could not restore defaults", catalogError || "The catalog is still loading.");
      return;
    }
    const ok = await confirm({
      title: "Restore the default sources?",
      message:
        "Any of the Simplify internships, Simplify new grad and SpeedyApply lists you removed will be added back. Your other sources are untouched.",
      confirmLabel: "Restore",
    });
    if (!ok) return;
    const result = restoreDefaults(sources, catalog);
    if (result.added) onChange(result.sources);
    if (result.missing.length)
      toast.error("Some defaults are not in the catalog", result.missing.join(", "));
    else if (!result.added)
      toast.info("Nothing to restore", "All default sources are already there.");
  }

  return (
    <section aria-label="Sources" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-xl text-sm text-ink-muted">
          Where the nightly run and <strong>Find jobs</strong> look for postings. Turn a source off
          to skip it, or remove it for good.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => void restore()}>
            Restore defaults
          </Button>
          <Button variant="primary" onClick={() => setAdding(true)}>
            Add source
          </Button>
        </div>
      </div>

      {saveError && (
        <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          Your sources could not be saved: {saveError}
        </p>
      )}

      {sources.length === 0 ? (
        <EmptyState
          title="No sources yet"
          action={
            <Button variant="primary" onClick={() => setAdding(true)}>
              Add a source
            </Button>
          }
        >
          Nothing will be searched until you add one. Pick from the catalog, paste a GitHub job
          list, or set up a keyword search.
        </EmptyState>
      ) : (
        <ul className="space-y-3">
          {sources.map((source) => (
            <SourceRow
              key={source.id}
              source={source}
              update={availableUpdate(source, catalog)}
              open={editing === source.id}
              onToggleOpen={() => setEditing(editing === source.id ? null : source.id)}
              onChange={(next) => update(source.id, next)}
              onRemove={() => void remove(source)}
            />
          ))}
        </ul>
      )}

      {adding && (
        <AddSourceDialog
          sources={sources}
          catalog={catalog}
          catalogError={catalogError}
          onAdd={(source) => onChange([...sources, source])}
          onClose={() => setAdding(false)}
        />
      )}
    </section>
  );
}

function SourceRow({
  source,
  update,
  open,
  onToggleOpen,
  onChange,
  onRemove,
}: {
  source: SourceConfig;
  update: CatalogEntry | null;
  open: boolean;
  onToggleOpen: () => void;
  onChange: (next: SourceConfig) => void;
  onRemove: () => void;
}) {
  const name = sourceDisplayName(source);
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(name);
  const [reviewing, setReviewing] = useState(false);

  function commitName() {
    setRenaming(false);
    const next = draftName.trim();
    if (next && next !== name) onChange({ ...source, name: next });
    else setDraftName(name);
  }

  return (
    <li className="rounded-lg border border-line bg-panel p-3">
      <div className="flex flex-wrap items-start gap-3">
        <input
          type="checkbox"
          role="switch"
          aria-label={`${name} on`}
          aria-checked={source.enabled}
          className="mt-1 h-4 w-4"
          checked={source.enabled}
          onChange={(e) => onChange({ ...source, enabled: e.target.checked })}
        />
        <div className="min-w-0 flex-1">
          {renaming ? (
            <input
              autoFocus
              aria-label={`Name for ${name}`}
              className="field w-full max-w-sm text-sm"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onBlur={commitName}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitName();
                if (e.key === "Escape") {
                  setDraftName(name);
                  setRenaming(false);
                }
              }}
            />
          ) : (
            <p className="flex flex-wrap items-center gap-2 font-medium">
              <span className={source.enabled ? "" : "text-ink-muted"}>{name}</span>
              <button
                type="button"
                className="text-xs font-normal text-ink-muted underline hover:text-accent"
                aria-label={`Rename ${name}`}
                onClick={() => {
                  setDraftName(name);
                  setRenaming(true);
                }}
              >
                Rename
              </button>
              {update && (
                <span className="rounded-full bg-warn-soft px-2 py-0.5 text-micro font-semibold text-warn">
                  Update available
                </span>
              )}
            </p>
          )}
          <div className="mt-1 flex flex-wrap gap-1 text-micro text-ink-muted">
            <span className="rounded-full bg-paper px-2 py-0.5">
              {sourceKindLabel(source.kind)}
            </span>
            {isReadmeKind(source.kind) && source.categories.length > 0 && (
              <span className="rounded-full bg-paper px-2 py-0.5">
                {source.categories.length} categor{source.categories.length === 1 ? "y" : "ies"}
              </span>
            )}
            {source.kind === "ats_board" && (
              <span className="rounded-full bg-paper px-2 py-0.5">
                {(source.boards ?? []).length} compan
                {(source.boards ?? []).length === 1 ? "y" : "ies"}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" aria-expanded={open} onClick={onToggleOpen}>
            {open ? "Done" : "Edit"}
          </Button>
          <Button size="sm" variant="ghost" aria-label={`Remove ${name}`} onClick={onRemove}>
            Remove
          </Button>
        </div>
      </div>

      {update && (
        <div className="mt-2">
          {reviewing ? (
            <UpdateDiff
              source={source}
              entry={update}
              onCancel={() => setReviewing(false)}
              onApply={() => {
                onChange(applyCatalogUpdate(source, update));
                setReviewing(false);
              }}
            />
          ) : (
            <button
              type="button"
              className="text-xs text-accent underline"
              onClick={() => setReviewing(true)}
            >
              Review update
            </button>
          )}
        </div>
      )}

      {open && (
        <div className="mt-2">
          {source.kind === "ats_board" ? (
            <WatchlistEditor source={source} onChange={onChange} />
          ) : source.kind === "job_search" ? (
            <JobSearchEditor source={source} onChange={onChange} />
          ) : (
            <CategoryPicker source={source} onChange={onChange} />
          )}
        </div>
      )}
      <div className="mt-2">
        <SourceTest source={source} />
      </div>
    </li>
  );
}

function UpdateDiff({
  source,
  entry,
  onApply,
  onCancel,
}: {
  source: SourceConfig;
  entry: CatalogEntry;
  onApply: () => void;
  onCancel: () => void;
}) {
  const diff = catalogDiff(source, entry);
  const nothing = !diff.url && diff.added.length === 0 && diff.removed.length === 0;
  return (
    <div
      role="region"
      aria-label={`Update for ${sourceDisplayName(source)}`}
      className="space-y-2 rounded-md border border-line bg-paper p-3 text-xs"
    >
      <p className="font-medium">
        Version {source.catalog_version || "?"} → {entry.version}
        {entry.fields.length > 0 && (
          <span className="ml-2 font-normal text-ink-muted">
            {entry.fields.map((f) => FIELD_LABELS[f] ?? f).join(" · ")}
          </span>
        )}
      </p>
      {diff.url && (
        <p className="break-all">
          <span className="font-medium">Link:</span> <s className="text-danger">{diff.url.from}</s>{" "}
          → <span className="text-accent">{diff.url.to}</span>
        </p>
      )}
      {diff.added.length > 0 && <p className="text-accent">+ {diff.added.join(" · ")}</p>}
      {diff.removed.length > 0 && <p className="text-danger">− {diff.removed.join(" · ")}</p>}
      {nothing && <p className="text-ink-muted">Only the version number changes.</p>}
      <div className="flex gap-2">
        <Button size="sm" variant="primary" onClick={onApply}>
          Update
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Not now
        </Button>
      </div>
    </div>
  );
}
