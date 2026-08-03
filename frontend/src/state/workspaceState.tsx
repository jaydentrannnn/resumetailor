import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  type Workspace,
  activateWorkspace,
  createWorkspace,
  deleteWorkspace,
  fetchWorkspaces,
  renameWorkspace,
} from "../api";

type WorkspaceStateValue = {
  workspaces: Workspace[];
  activeId: string | null;
  activeLabel: string | null;
  /** True until the first `GET /api/workspaces` resolves. */
  loading: boolean;
  /** True while an activation is in flight — blocks the switcher and the Run button. */
  switching: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  activate: (id: string) => Promise<void>;
  create: (label: string, copyFrom?: string | null) => Promise<void>;
  rename: (id: string, label: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
};

const WorkspaceStateContext = createContext<WorkspaceStateValue | null>(null);

/**
 * Owns the profile registry above everything else in the app. Never remounts on a
 * switch — `App.tsx` keys `RunProvider` / `EditorProvider` / `TemplateProvider` on
 * `activeId`, so a switch discards their cached state by unmounting and remounting
 * them, rather than by resetting anything in this provider.
 */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetchWorkspaces();
      setWorkspaces(res.entries);
      setActiveId(res.active_id);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchWorkspaces();
        if (cancelled) return;
        setWorkspaces(res.entries);
        setActiveId(res.active_id);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const activate = useCallback(async (id: string) => {
    setSwitching(true);
    setError(null);
    try {
      const res = await activateWorkspace(id);
      setWorkspaces(res.entries);
      // Set last: this is the state change that keys the remount in App.tsx, so it
      // must not fire until the server confirms the switch actually happened.
      setActiveId(res.active_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setSwitching(false);
    }
  }, []);

  const create = useCallback(async (label: string, copyFrom?: string | null) => {
    setError(null);
    try {
      const res = await createWorkspace(label, copyFrom ?? null);
      setWorkspaces(res.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, []);

  const rename = useCallback(async (id: string, label: string) => {
    setError(null);
    try {
      const res = await renameWorkspace(id, label);
      setWorkspaces(res.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, []);

  const remove = useCallback(async (id: string) => {
    setError(null);
    try {
      const res = await deleteWorkspace(id);
      setWorkspaces(res.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, []);

  const activeLabel = useMemo(
    () => workspaces.find((w) => w.id === activeId)?.label ?? null,
    [workspaces, activeId],
  );

  const value = useMemo<WorkspaceStateValue>(
    () => ({
      workspaces,
      activeId,
      activeLabel,
      loading,
      switching,
      error,
      refresh,
      activate,
      create,
      rename,
      remove,
    }),
    [workspaces, activeId, activeLabel, loading, switching, error, refresh, activate, create, rename, remove],
  );

  return (
    <WorkspaceStateContext.Provider value={value}>{children}</WorkspaceStateContext.Provider>
  );
}

/**
 * Access the profile registry. Must be used within `WorkspaceProvider`.
 */
export function useWorkspaceState(): WorkspaceStateValue {
  const ctx = useContext(WorkspaceStateContext);
  if (!ctx) {
    throw new Error("useWorkspaceState must be used within WorkspaceProvider");
  }
  return ctx;
}
