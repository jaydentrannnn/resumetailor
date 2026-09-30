import { useCallback, useEffect, useRef, useState } from "react";
import type { useSearchParams } from "react-router-dom";
import { listApplications, type ApplicationsList } from "../../api";

/** Which list a table shows: "review" = Needs you, "queue" = In progress, "archive" = Done. */
export type Scope = "queue" | "review" | "archive";

const selectionCache = new Map<string, Set<string>>();

/**
 * One paginated, filterable application list whose search, filter, sort and page live
 * in the URL (prefixed by scope), with a selection that survives leaving the page.
 */
export function useApplicationTable(
  scope: Scope,
  workspaceId: string,
  params: URLSearchParams,
  setParams: ReturnType<typeof useSearchParams>[1],
  enabled: boolean,
) {
  const key = useCallback((name: string) => `${scope}_${name}`, [scope]);
  const [data, setData] = useState<ApplicationsList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [selected, setSelectedState] = useState(
    () => new Set(selectionCache.get(`${workspaceId}:${scope}`) ?? []),
  );
  const sequence = useRef(0);
  const q = params.get(key("q")) ?? "";
  const status = params.get(key("status")) ?? "";
  const page = Math.max(0, (Number(params.get(key("page"))) || 1) - 1);
  const size = [25, 50, 100].includes(Number(params.get(key("size"))))
    ? Number(params.get(key("size")))
    : 25;
  const sort = params.get(key("sort")) ?? (scope === "archive" ? "archived_at" : scope === "review" ? "status_at" : "posted_at");
  const direction: "asc" | "desc" = params.get(key("direction")) === "asc" ? "asc" : "desc";
  const [search, setSearch] = useState(q);
  useEffect(() => {
    const id = window.setTimeout(() => setSearch(q), 250);
    return () => window.clearTimeout(id);
  }, [q]);
  function setSelected(next: Set<string>) {
    setSelectedState(next);
    selectionCache.set(`${workspaceId}:${scope}`, next);
  }
  function change(values: Record<string, string>, reset = true) {
    sequence.current++;
    if (reset) setSelected(new Set());
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        Object.entries(values).forEach(([field, value]) =>
          value ? next.set(key(field), value) : next.delete(key(field)),
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
      q: search.trim(),
      status: status || undefined,
      sort,
      direction,
      limit: size,
      offset: page * size,
    })
      .then((result) => {
        if (current !== sequence.current) return;
        setData(result);
        setError(null);
        setSelectedState((previous) => {
          const ids = new Set(result.applications.map((row) => row.source_job_id));
          const next = new Set([...previous].filter((id) => ids.has(id)));
          if (next.size === previous.size) return previous; // unchanged: keep the reference
          selectionCache.set(`${workspaceId}:${scope}`, next);
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
    enabled,
    scope,
    search,
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
    error,
    loading,
    selected,
    setSelected,
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
