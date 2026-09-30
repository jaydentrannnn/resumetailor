import { useCallback, useEffect, useState } from "react";
import { fetchSecrets, fetchSourcesStatus, type SourcesStatus } from "../../api";
import { PROVIDER_KEYS, type SearchProvider } from "../../lib/sources";

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
