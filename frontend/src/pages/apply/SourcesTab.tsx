import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  fetchSourceCatalog,
  type ResolvedBoard,
  type SourceCatalog,
  type SourceConfig,
  type SourceField,
  type SourcesStatus,
} from "../../api";
import { RowActionsMenu } from "../../components/TableControls";
import { Button } from "../../components/ui";
import { describe } from "../../lib/errors";
import {
  availableUpdate,
  duplicateSource,
  FIELD_LABELS,
  groupOf,
  newJobSearchSource,
  newReadmeSource,
  PROVIDER_LABELS,
  providerOf,
  recommendedEntries,
  restoreDefaults,
  restoreRemoved,
  SOURCE_FIELDS,
  sourceDisplayName,
  sourceFromCatalog,
  sourcesHeadline,
  withoutSources,
  type SearchProvider,
} from "../../lib/sources";
import { useToast } from "../../lib/toast";
import { addBoard, newWatchlistSource } from "../../lib/watchlist";
import { BoardTargetDialog, CatalogDialog, ConnectDialog, type KnownInspection } from "./AddFlows";
import { useProviderConnections } from "./sourceHooks";
import { SourcePanel, type SaveState } from "./SourcePanel";
import { SourceRow } from "./SourceRow";

const DISMISS_KEY = "rt:sources-recommended-dismissed";

type Flow =
  | { type: "catalog" }
  /** A source being added: the panel opens on this draft; nothing is saved until Add. */
  | { type: "new"; source: SourceConfig; sections: string[] | null }
  | { type: "board"; board: ResolvedBoard };

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

function writeDismissed(on: boolean) {
  try {
    if (on) localStorage.setItem(DISMISS_KEY, "1");
    else localStorage.removeItem(DISMISS_KEY);
  } catch {
    /* a per-viewer convenience only */
  }
}

/**
 * The job-sources page body: every place the nightly run looks for jobs, in three
 * always-visible groups (job lists, search engines, company watchlists). Every row has the
 * same controls, and adding or editing opens the same side panel. Changes go through
 * `onChange` (the settings autosave); `saveError` shows a server validation error.
 */
export function SourcesTab({
  sources,
  onChange,
  saveError,
  saveState = "saved",
  onFlush,
  status = null,
  fields = [],
  onFieldsChange,
}: {
  sources: SourceConfig[];
  onChange: (next: SourceConfig[]) => void;
  saveError: string | null;
  saveState?: SaveState;
  /** Writes any pending autosave now (the side panel calls it on close). */
  onFlush?: () => void | Promise<unknown>;
  /** How each source did on the latest run; null before the first or when unavailable. */
  status?: SourcesStatus | null;
  /** The job fields this profile searches for (`apply.fields`). */
  fields?: SourceField[];
  onFieldsChange?: (fields: SourceField[]) => void;
}) {
  const toast = useToast();
  const providers = useProviderConnections();
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [flow, setFlow] = useState<Flow | null>(null);
  const [connecting, setConnecting] = useState<SearchProvider | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState(readDismissed);
  const [pickingFields, setPickingFields] = useState(false);

  // Toast actions outlive the render that created them, so they read the latest values.
  const sourcesRef = useRef(sources);
  sourcesRef.current = sources;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const commit = (next: SourceConfig[]) => onChangeRef.current(next);

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
    commit(sourcesRef.current.map((s) => (s.id === id ? next : s)));
  const append = (source: SourceConfig) => commit([...sourcesRef.current, source]);
  const selectedIds = new Set(sources.filter((s) => selected.has(s.id)).map((s) => s.id));
  const editingSource = editing ? sources.find((s) => s.id === editing) : undefined;

  function remove(ids: ReadonlySet<string>) {
    const { kept, removed } = withoutSources(sourcesRef.current, ids);
    if (removed.length === 0) return;
    commit(kept);
    setSelected(new Set());
    if (editing && ids.has(editing)) setEditing(null);
    toast.show({
      kind: "info",
      title:
        removed.length === 1
          ? `Removed ${sourceDisplayName(removed[0].source)}`
          : `Removed ${removed.length} sources`,
      timeoutMs: 10000,
      action: {
        label: "Undo",
        onClick: () => commit(restoreRemoved(sourcesRef.current, removed)),
      },
    });
  }

  function setEnabled(ids: ReadonlySet<string>, enabled: boolean) {
    commit(sourcesRef.current.map((s) => (ids.has(s.id) ? { ...s, enabled } : s)));
  }

  function added(source: SourceConfig, close = true) {
    append(source);
    toast.success(`Added ${sourceDisplayName(source)}`);
    if (close) setFlow(null);
  }

  const connections = providers.connected;
  function newSearch() {
    // Start on an engine that is connected, so the first search can run right away.
    const provider =
      connections && !connections.adzuna && connections.usajobs ? "usajobs" : "adzuna";
    setFlow({
      type: "new",
      source: newJobSearchSource(sourcesRef.current, { provider }),
      sections: null,
    });
  }
  function newWatchlist(board?: ResolvedBoard) {
    setFlow({
      type: "new",
      source: {
        ...newWatchlistSource(undefined, sourcesRef.current),
        name: "",
        boards: board ? [{ ats: board.ats, slug: board.slug, company: board.company }] : [],
      },
      sections: null,
    });
  }
  function newList(url: string, inspection: KnownInspection) {
    setFlow({
      type: "new",
      source: newReadmeSource(sourcesRef.current, url, inspection.kind, "", []),
      sections: inspection.sections,
    });
  }

  function restore() {
    if (!catalog) {
      toast.error("Could not restore defaults", catalogError || "The catalog is still loading.");
      return;
    }
    const before = new Set(sourcesRef.current.map((s) => s.id));
    const result = restoreDefaults(sourcesRef.current, catalog);
    if (result.added) {
      commit(result.sources);
      const ids = new Set(result.sources.filter((s) => !before.has(s.id)).map((s) => s.id));
      toast.show({
        kind: "info",
        title: `Restored ${result.added} default source${result.added === 1 ? "" : "s"}`,
        timeoutMs: 10000,
        action: {
          label: "Undo",
          onClick: () => commit(withoutSources(sourcesRef.current, ids).kept),
        },
      });
    }
    if (result.missing.length)
      toast.error("Some defaults are not in the catalog", result.missing.join(", "));
    else if (!result.added)
      toast.info("Nothing to restore", "All default sources are already there.");
  }

  const searchNotice = (source: SourceConfig): string | undefined => {
    if (source.kind !== "job_search" || providers.connected?.[providerOf(source)] !== false)
      return undefined;
    return `Connect ${PROVIDER_LABELS[providerOf(source)]} to run this search.`;
  };

  function renderRow(source: SourceConfig) {
    return (
      <SourceRow
        key={source.id}
        source={source}
        run={status?.sources[source.id]}
        selected={selectedIds.has(source.id)}
        update={availableUpdate(source, catalog)}
        notice={searchNotice(source)}
        keysSaved={
          source.kind === "job_search" && connections ? connections[providerOf(source)] : null
        }
        onSelect={(on) =>
          setSelected((prev) => {
            const next = new Set(prev);
            if (on) next.add(source.id);
            else next.delete(source.id);
            return next;
          })
        }
        onChange={(next) => update(source.id, next)}
        onEdit={() => setEditing(source.id)}
        onDuplicate={() => commit(duplicateSource(source, sourcesRef.current))}
        onRemove={() => remove(new Set([source.id]))}
      />
    );
  }

  const lists = sources.filter((s) => groupOf(s.kind) === "lists");
  const searches = sources.filter((s) => groupOf(s.kind) === "search");
  const watchlists = sources.filter((s) => groupOf(s.kind) === "watchlists");
  const recommended = recommendedEntries(catalog, sources, fields);
  const showRecommended =
    !!onFieldsChange && !dismissed && (fields.length === 0 || recommended.length > 0);

  return (
    <section aria-label="Sources" className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium" aria-live="polite">
            {sourcesHeadline(sources, status?.last_run_at)}
          </p>
          <p className="max-w-xl text-sm text-ink-muted">
            Where the nightly run and <strong>Find jobs</strong> look for postings. Turn a source
            off to skip it, or remove it (you can undo).
          </p>
        </div>
        <div className="flex items-center gap-2">
          {sources.length > 0 && (
            <label className="flex items-center gap-2 text-xs text-ink-muted">
              <input
                type="checkbox"
                aria-label="Select all sources"
                className="h-4 w-4 accent-[var(--color-accent)]"
                checked={selectedIds.size === sources.length}
                onChange={(e) =>
                  setSelected(e.target.checked ? new Set(sources.map((s) => s.id)) : new Set())
                }
              />
              Select all
            </label>
          )}
          <RowActionsMenu
            label="More source actions"
            items={[
              { label: "Restore defaults", action: restore },
              ...(onFieldsChange
                ? [
                    {
                      label: "Change fields",
                      action: () => {
                        setDismissed(false);
                        writeDismissed(false);
                        setPickingFields(true);
                      },
                    },
                    {
                      label: "Show recommendations",
                      action: () => {
                        setDismissed(false);
                        writeDismissed(false);
                      },
                    },
                  ]
                : []),
            ]}
          />
        </div>
      </div>

      {saveError && !editingSource && (
        <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          Your sources could not be saved: {saveError}
        </p>
      )}

      {(showRecommended || pickingFields) && onFieldsChange && (
        <RecommendedStrip
          fields={fields}
          recommended={recommended}
          picking={pickingFields}
          onPicking={setPickingFields}
          onFieldsChange={onFieldsChange}
          onAdd={(entry) => added(sourceFromCatalog(entry, sourcesRef.current), false)}
          onDismiss={() => {
            setDismissed(true);
            writeDismissed(true);
            setPickingFields(false);
          }}
        />
      )}

      {selectedIds.size > 0 && (
        <div
          role="toolbar"
          aria-label="Selected sources"
          className="flex flex-wrap items-center gap-2 rounded-lg border border-accent/40 bg-accent-soft/40 p-2 text-sm"
        >
          <span className="px-1 font-medium">{selectedIds.size} selected</span>
          <Button size="sm" variant="secondary" onClick={() => setEnabled(selectedIds, true)}>
            Turn on
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setEnabled(selectedIds, false)}>
            Turn off
          </Button>
          <Button size="sm" variant="secondary" onClick={() => remove(selectedIds)}>
            Remove
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      )}

      <Group
        id="lists"
        title="Job lists"
        explanation="GitHub lists of internships and new-grad roles, from the catalog or any repo you paste."
        action={
          <Button size="sm" variant="secondary" onClick={() => setFlow({ type: "catalog" })}>
            + Add job list
          </Button>
        }
        empty="No job lists yet."
        rows={lists.map(renderRow)}
      />

      <Group
        id="search"
        title="Search engines"
        explanation="Keyword searches through Adzuna or USAJobs. Connect a free API key once, then add as many searches as you like."
        action={
          <Button size="sm" variant="secondary" onClick={newSearch}>
            + Add search
          </Button>
        }
        extra={
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
            {(["adzuna", "usajobs"] as const).map((provider) => (
              <ProviderStatus
                key={provider}
                provider={provider}
                connected={connections ? connections[provider] : null}
                onConnect={() => setConnecting(provider)}
              />
            ))}
          </div>
        }
        empty="No searches yet."
        rows={searches.map(renderRow)}
      />

      <Group
        id="watchlists"
        title="Company watchlists"
        explanation="Companies whose careers pages are read directly (Greenhouse, Lever, Ashby and more). The best way to catch finance and consulting roles."
        action={
          <Button size="sm" variant="secondary" onClick={() => newWatchlist()}>
            + Add watchlist
          </Button>
        }
        empty="No watchlists yet."
        rows={watchlists.map(renderRow)}
      />

      {flow?.type === "catalog" && (
        <CatalogDialog
          sources={sources}
          catalog={catalog}
          catalogError={catalogError}
          fields={fields}
          onAdd={(source) => added(source, false)}
          onReadme={newList}
          onBoard={(board) =>
            sourcesRef.current.some((s) => s.kind === "ats_board")
              ? setFlow({ type: "board", board })
              : newWatchlist(board)
          }
          onClose={() => setFlow(null)}
        />
      )}
      {flow?.type === "board" && (
        <BoardTargetDialog
          board={flow.board}
          watchlists={watchlists}
          onNew={() => newWatchlist(flow.board)}
          onAddTo={(id) => {
            const target = sourcesRef.current.find((s) => s.id === id);
            if (target) {
              const { ats, slug, company } = flow.board;
              update(id, {
                ...target,
                boards: addBoard(target.boards ?? [], { ats, slug, company }),
              });
              toast.success(`Added ${flow.board.company || flow.board.slug}`);
            }
            setFlow(null);
          }}
          onClose={() => setFlow(null)}
        />
      )}
      {flow?.type === "new" && (
        <SourcePanel
          mode="new"
          source={flow.source}
          initialSections={flow.sections}
          connections={connections}
          onConnect={setConnecting}
          onAdd={added}
          onClose={() => setFlow(null)}
        />
      )}
      {editingSource && (
        <SourcePanel
          source={editingSource}
          saveState={saveState}
          saveError={saveError}
          connections={connections}
          onConnect={setConnecting}
          onChange={(next) => update(editingSource.id, next)}
          onRemove={() => remove(new Set([editingSource.id]))}
          onClose={() => {
            setEditing(null);
            void onFlush?.();
          }}
        />
      )}
      {connecting && (
        <ConnectDialog
          provider={connecting}
          savedKeys={providers.savedKeys}
          onSaved={providers.refresh}
          onClose={() => setConnecting(null)}
        />
      )}
    </section>
  );
}

/** A group's heading, one-line explanation and add button; an empty group keeps all three. */
function Group({
  id,
  title,
  explanation,
  action,
  extra,
  empty,
  rows,
}: {
  id: string;
  title: string;
  explanation: string;
  action: ReactNode;
  /** A line between the heading and the rows (the search engines' connection status). */
  extra?: ReactNode;
  empty: string;
  rows: ReactNode[];
}) {
  return (
    <section aria-labelledby={`sources-group-${id}`} className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 max-w-xl">
          <h3 id={`sources-group-${id}`} className="font-semibold">
            {title}
          </h3>
          <p className="text-sm text-ink-muted">{explanation}</p>
        </div>
        {action}
      </div>
      {extra}
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line px-3 py-2 text-sm text-ink-muted">
          {empty}
        </p>
      ) : (
        <ul className="space-y-2">{rows}</ul>
      )}
    </section>
  );
}

/** One search engine's connection: whether its keys are saved, and how to change them. */
function ProviderStatus({
  provider,
  connected,
  onConnect,
}: {
  provider: SearchProvider;
  connected: boolean | null;
  onConnect: () => void;
}) {
  const label = PROVIDER_LABELS[provider];
  return (
    <span role="group" aria-label={label} className="flex items-center gap-1.5">
      <span className="font-medium">{label}</span>
      <span
        className={
          connected ? "text-success" : connected === false ? "text-warn" : "text-ink-muted"
        }
      >
        {connected ? "● Connected" : connected === false ? "○ Not connected" : "Checking…"}
      </span>
      {connected !== null && (
        <button
          type="button"
          className="text-accent underline"
          aria-label={connected ? `Change ${label} keys` : `Connect ${label}`}
          onClick={onConnect}
        >
          {connected ? "Change keys" : "Connect"}
        </button>
      )}
    </span>
  );
}

/** Catalog lists tagged with the user's fields that they do not have yet, one click each. */
function RecommendedStrip({
  fields,
  recommended,
  picking,
  onPicking,
  onFieldsChange,
  onAdd,
  onDismiss,
}: {
  fields: SourceField[];
  recommended: ReturnType<typeof recommendedEntries>;
  picking: boolean;
  onPicking: (on: boolean) => void;
  onFieldsChange: (fields: SourceField[]) => void;
  onAdd: (entry: ReturnType<typeof recommendedEntries>[number]) => void;
  onDismiss: () => void;
}) {
  return (
    <div
      role="region"
      aria-label="Recommended for your fields"
      className="space-y-2 rounded-lg border border-line bg-paper p-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium">Recommended for your fields</p>
        {fields.length > 0 && !picking && (
          <Button size="sm" variant="ghost" onClick={() => onPicking(true)}>
            Change fields
          </Button>
        )}
        <Button
          className="ml-auto"
          size="sm"
          variant="ghost"
          aria-label="Dismiss recommendations"
          onClick={onDismiss}
        >
          ×
        </Button>
      </div>
      {(fields.length === 0 || picking) && (
        <div className="space-y-2">
          <p className="text-xs text-ink-muted">
            {fields.length === 0
              ? "Pick the kinds of jobs you want and we will suggest job lists for them."
              : "Suggestions follow these fields."}
          </p>
          <div role="group" aria-label="Your fields" className="flex flex-wrap gap-1.5">
            {SOURCE_FIELDS.map((field) => {
              const on = fields.includes(field);
              return (
                <button
                  key={field}
                  type="button"
                  aria-pressed={on}
                  className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-muted hover:border-accent"}`}
                  onClick={() =>
                    onFieldsChange(on ? fields.filter((f) => f !== field) : [...fields, field])
                  }
                >
                  {FIELD_LABELS[field]}
                </button>
              );
            })}
          </div>
          {picking && (
            <Button size="sm" variant="secondary" onClick={() => onPicking(false)}>
              Done
            </Button>
          )}
        </div>
      )}
      {fields.length > 0 && recommended.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {recommended.map((entry) => (
            <li key={entry.id}>
              <Button
                size="sm"
                variant="secondary"
                title={entry.description}
                aria-label={`Add ${entry.name}`}
                onClick={() => onAdd(entry)}
              >
                + {entry.name}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
