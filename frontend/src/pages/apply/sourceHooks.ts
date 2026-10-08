import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchSecrets,
  fetchSourcesStatus,
  fetchSourceCatalog,
  type SourcesStatus,
  type SourceConfig,
  type SourceCatalog,
  type ResolvedBoard,
} from "../../api";
import {
  PROVIDER_KEYS,
  PROVIDER_LABELS,
  providerOf,
  newJobSearchSource,
  newReadmeSource,
  restoreDefaults,
  restoreRemoved,
  sourceDisplayName,
  withoutSources,
  type SearchProvider,
} from "../../lib/sources";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { newWatchlistSource } from "../../lib/watchlist";
import type { KnownInspection } from "./AddFlows";

/**
 * Per-source results of the latest run. ``refreshKey`` re-fetches when it changes (a run
 * just finished). A failed fetch leaves the health lines at "Not run yet" rather than
 * breaking the tab, so an older backend without the endpoint still renders.
 */
export function useSourcesStatus(refreshKey: unknown = 0): SourcesStatus | null {
  const [status, setStatus] = useState<SourcesStatus | null>(null);
  useEffect(() => {
    let live = true;
    fetchSourcesStatus()
      .then((next) => live && setStatus(next))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [refreshKey]);
  return status;
}

export type ProviderConnections = {
  /** Which search engines have all their keys saved; null while loading. */
  connected: Record<SearchProvider, boolean> | null;
  /** The key names that are saved (so the Connect dialog can say "saved"). */
  savedKeys: Set<string>;
  refresh: () => void;
};

/** Whether Adzuna and USAJobs each have every key saved (values are never read back). */
export function useProviderConnections(): ProviderConnections {
  const [saved, setSaved] = useState<Set<string> | null>(null);
  const refresh = useCallback(() => {
    fetchSecrets()
      .then((res) => setSaved(new Set(res.secrets.filter((s) => s.set).map((s) => s.name))))
      .catch(() => setSaved(new Set()));
  }, []);
  useEffect(refresh, [refresh]);
  const has = (provider: SearchProvider) =>
    saved !== null && PROVIDER_KEYS[provider].every((key) => saved.has(key.name));
  return {
    connected: saved === null ? null : { adzuna: has("adzuna"), usajobs: has("usajobs") },
    savedKeys: saved ?? new Set(),
    refresh,
  };
}

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

export function writeDismissed(on: boolean) {
  try {
    if (on) localStorage.setItem(DISMISS_KEY, "1");
    else localStorage.removeItem(DISMISS_KEY);
  } catch {
    /* a per-viewer convenience only */
  }
}

/** Source operations shared by the three group tiles and their dialogs. */
export function useSourcesController(
  sources: SourceConfig[],
  onChange: (next: SourceConfig[]) => void,
) {
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

  return {
    toast,
    providers,
    catalog,
    catalogError,
    flow,
    setFlow,
    connecting,
    setConnecting,
    editingSource,
    setEditing,
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
    newList,
    restore,
    searchNotice,
  };
}
