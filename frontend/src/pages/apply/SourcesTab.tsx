import { type SourceConfig, type SourceField, type SourcesStatus } from "../../api";
import { Button, SelectionBar, StatusMark } from "../../components/ui";
import {
  availableUpdate,
  duplicateSource,
  groupOf,
  PROVIDER_LABELS,
  providerOf,
  recommendedEntries,
  sourceFromCatalog,
  type SearchProvider,
} from "../../lib/sources";
import { useSourcesController, writeDismissed } from "./sourceHooks";
import { SourceFlows, type SaveState } from "./SourcePanel";
import { SourceRow } from "./SourceRow";
import { SourceGroup, SourceToolbar } from "./SourceGroup";
import { RecommendedStrip } from "./RecommendedStrip";

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
  const controller = useSourcesController(sources, onChange);
  const {
    catalog,
    setFlow,
    editingSource,
    setEditing,
    setConnecting,
    selectedIds,
    setSelected,
    dismissed,
    setDismissed,
    pickingFields,
    setPickingFields,
    sourcesRef,
    commit,
    update,
    remove,
    setEnabled,
    added,
    connections,
    newSearch,
    newWatchlist,
    searchNotice,
  } = controller;

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
      <SourceToolbar
        sources={sources}
        status={status}
        controller={controller}
        canChangeFields={!!onFieldsChange}
      />

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
        <SelectionBar
          count={selectedIds.size}
          noun="selected"
          clearLabel="Clear"
          label="Selected sources"
          onClear={() => setSelected(new Set())}
        >
          <Button size="sm" variant="secondary" onClick={() => setEnabled(selectedIds, true)}>
            Turn on
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setEnabled(selectedIds, false)}>
            Turn off
          </Button>
          <Button size="sm" variant="secondary" onClick={() => remove(selectedIds)}>
            Remove
          </Button>
        </SelectionBar>
      )}

      <SourceGroup
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

      <SourceGroup
        id="search"
        title="Search engines"
        explanation="Keyword searches through Adzuna or USAJobs. Connect a free API key once, then add as many searches as you like."
        action={
          <Button size="sm" variant="secondary" onClick={newSearch}>
            + Add search
          </Button>
        }
        extra={
          <div className="divide-y divide-line text-xs">
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

      <SourceGroup
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

      <SourceFlows
        controller={controller}
        sources={sources}
        fields={fields}
        saveState={saveState}
        saveError={saveError}
        onFlush={onFlush}
      />
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
    <span
      role="group"
      aria-label={label}
      className="flex flex-wrap items-center gap-2 py-2 first:pt-0 last:pb-0"
    >
      <span className="font-medium">{label}</span>
      <span
        className={
          connected ? "text-success" : connected === false ? "text-attn" : "text-ink-muted"
        }
      >
        {connected ? (
          "● Connected"
        ) : (
          <span className="inline-flex items-center gap-1.5">
            {connected === null && <StatusMark tone="live" />}
            {connected === false ? "○ Not connected" : "Checking…"}
          </span>
        )}
      </span>
      {connected !== null && (
        <button
          type="button"
          className="ml-auto text-accent underline"
          aria-label={connected ? `Change ${label} keys` : `Connect ${label}`}
          onClick={onConnect}
        >
          {connected ? "Change keys" : "Connect"}
        </button>
      )}
    </span>
  );
}
