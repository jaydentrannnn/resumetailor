import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { useSearchParams } from "react-router-dom";
import { listApplications, type ApplicationRow, type ApplicationsList } from "../../api";

/** Which list a table shows: "review" = Needs you, "queue" = In progress, "archive" = Done. */
export type Scope = "queue" | "review" | "archive";

// id -> the row as last seen, so a selection can outlive the page it was made on.
type Selection = Map<string, ApplicationRow>;
const selectionCache = new Map<string, Selection>();

/**
 * One paginated, filterable application list whose filter, sort and page live in the
 * URL (prefixed by scope), with a selection that survives paging, resizing the page and
 * leaving the screen. `q` is the page-wide search, already debounced by the caller.
 */
export function useApplicationTable(
  scope: Scope,
  workspaceId: string,
  params: URLSearchParams,
  setParams: ReturnType<typeof useSearchParams>[1],
  enabled: boolean,
  q = "",
) {
  const key = useCallback((name: string) => `${scope}_${name}`, [scope]);
  const cacheKey = `${workspaceId}:${scope}`;
  const [data, setData] = useState<ApplicationsList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  // The search `data` answers, so a caller can tell fresh results from the previous query's.
  const [dataQ, setDataQ] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>(
    () => new Map(selectionCache.get(cacheKey) ?? []),
  );
  const sequence = useRef(0);
  const visible = useRef({ sig: "", ids: new Set<string>() });
  const status = params.get(key("status")) ?? "";
  const page = Math.max(0, (Number(params.get(key("page"))) || 1) - 1);
  const size = [25, 50, 100].includes(Number(params.get(key("size"))))
    ? Number(params.get(key("size")))
    : 25;
  const sort =
    params.get(key("sort")) ??
    (scope === "archive" ? "archived_at" : scope === "review" ? "status_at" : "posted_at");
  const direction: "asc" | "desc" = params.get(key("direction")) === "asc" ? "asc" : "desc";
  const selected = useMemo(() => new Set(selection.keys()), [selection]);
  const selectedRows = useMemo(() => [...selection.values()], [selection]);

  function commit(next: Selection) {
    setSelection(next);
    selectionCache.set(cacheKey, next);
  }
  /** Replace the selection by id; rows not on screen keep the snapshot already held. */
  function setSelected(ids: Set<string>) {
    const onScreen = new Map((data?.applications ?? []).map((row) => [row.source_job_id, row]));
    const next: Selection = new Map();
    ids.forEach((id) => {
      const row = onScreen.get(id) ?? selection.get(id);
      if (row) next.set(id, row);
    });
    commit(next);
  }
  const clearSelection = () => commit(new Map());
  function deselect(ids: string[]) {
    commit(new Map([...selection].filter(([id]) => !ids.includes(id))));
  }
  // A new search is a new result set: nothing selected before it carries over.
  const lastQ = useRef(q);
  useEffect(() => {
    if (lastQ.current === q) return;
    lastQ.current = q;
    setSelection(new Map());
    selectionCache.set(cacheKey, new Map());
  }, [q, cacheKey]);
  function change(values: Record<string, string>) {
    sequence.current++;
    // Paging and resizing keep the selection; anything that changes which rows match drops it.
    if (["status", "sort", "direction"].some((field) => field in values)) clearSelection();
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        Object.entries(values).forEach(([field, value]) =>
          value && !(field === "page" && value === "1")
            ? next.set(key(field), value)
            : next.delete(key(field)),
        );
        if (!("page" in values)) next.delete(key("page"));
        return next;
      },
      { replace: true },
    );
  }
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    if (!enabled) return;
    const current = ++sequence.current;
    setLoading(true);
    listApplications({
      archive: scope === "archive" ? "archived" : "active",
      group: scope === "queue" ? "working" : scope === "review" ? "review" : undefined,
      q: q.trim(),
      status: status || undefined,
      sort,
      direction,
      limit: size,
      offset: page * size,
    })
      .then((result) => {
        if (current !== sequence.current) return;
        setData(result);
        setDataQ(q.trim());
        setError(null);
        // Rows that were on this very view a moment ago and are gone (moved on, archived)
        // leave the selection; rows on other pages stay.
        const sig = [q.trim(), status, sort, direction, size, page].join("|");
        const fresh = new Map(result.applications.map((row) => [row.source_job_id, row]));
        const gone = visible.current.sig === sig ? [...visible.current.ids] : [];
        visible.current = { sig, ids: new Set(fresh.keys()) };
        setSelection((previous) => {
          let changed = false;
          const next: Selection = new Map();
          previous.forEach((row, id) => {
            if (!fresh.has(id) && gone.includes(id)) {
              changed = true;
              return;
            }
            const latest = fresh.get(id);
            if (latest && latest !== row) changed = true;
            next.set(id, latest ?? row);
          });
          if (!changed) return previous; // unchanged: keep the reference
          selectionCache.set(cacheKey, next);
          return next;
        });
        const lastPage = Math.max(0, Math.ceil(result.total / size) - 1);
        if (page > lastPage)
          setParams(
            (previous) => {
              const next = new URLSearchParams(previous);
              if (lastPage) next.set(key("page"), String(lastPage + 1));
              else next.delete(key("page"));
              return next;
            },
            { replace: true },
          );
      })
      .catch((reason) => {
        if (current === sequence.current) setError(String(reason));
      })
      .finally(() => {
        if (current === sequence.current) setLoading(false);
      });
  }, [
    workspaceId,
    cacheKey,
    enabled,
    scope,
    q,
    status,
    sort,
    direction,
    size,
    page,
    revision,
    setParams,
    key,
  ]);
  return {
    data,
    dataQ,
    error,
    loading,
    selected,
    selectedRows,
    setSelected,
    clearSelection,
    deselect,
    q,
    status,
    page,
    size,
    sort,
    direction,
    change,
    refresh,
  };
}

export type ApplicationTableState = ReturnType<typeof useApplicationTable>;
