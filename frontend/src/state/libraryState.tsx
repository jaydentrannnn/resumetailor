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
  type LibraryEffective,
  type LibraryProposal,
  type LibraryState,
  type VocabularyEntry,
  type VocabularyKind,
  addVocabulary,
  approveLibraryProposals,
  fetchLibraries,
  generateLibraryProposals,
  rejectLibraryProposals,
  removeVocabulary,
  setVocabularyHidden,
} from "../api";

const EMPTY_EFFECTIVE: LibraryEffective = {
  term_count: 0,
  tag_alias_count: 0,
  verb_count: 0,
  fingerprint: "",
};

type LibraryStateValue = {
  entries: VocabularyEntry[];
  effective: LibraryEffective;
  diagnostics: string[];
  proposals: LibraryProposal[];
  /** Set only after a `generateProposals` call that partially failed. */
  proposalWarning: string | null;
  loading: boolean;
  /** True while any vocabulary edit or approve/reject is in flight. */
  busy: boolean;
  /** True while proposal generation runs — it can take a while, so the button gets its
   * own spinner rather than disabling everything. */
  generating: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /** Edits rethrow so the caller can show the failure next to the control. */
  add: (kind: VocabularyKind, value: string, target?: string) => Promise<void>;
  remove: (kind: VocabularyKind, value: string) => Promise<void>;
  setHidden: (kind: VocabularyKind, value: string, hidden: boolean) => Promise<void>;
  generateProposals: (jdText?: string) => Promise<void>;
  approveProposals: (ids: string[], targets?: Record<string, string>) => Promise<void>;
  rejectProposals: (ids: string[]) => Promise<void>;
};

const LibraryStateContext = createContext<LibraryStateValue | null>(null);

/**
 * Owns the vocabulary dictionary and the active profile's pending suggestions. The
 * dictionary and the user's additions are app-wide; only suggestions are per profile,
 * which is why this stays keyed on the active workspace in `App.tsx`.
 */
export function LibraryProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<VocabularyEntry[]>([]);
  const [effective, setEffective] = useState<LibraryEffective>(EMPTY_EFFECTIVE);
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [proposals, setProposals] = useState<LibraryProposal[]>([]);
  const [proposalWarning, setProposalWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyState = useCallback((next: LibraryState) => {
    setEntries(next.entries);
    setEffective(next.effective);
    setDiagnostics(next.diagnostics);
    setProposals(next.proposals);
    setProposalWarning(next.warning);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      applyState(await fetchLibraries());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [applyState]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** Run one mutation; `rethrow` leaves the error to the caller instead of `error`. */
  const mutate = useCallback(
    async (call: () => Promise<LibraryState>, rethrow: boolean) => {
      setBusy(true);
      setError(null);
      try {
        applyState(await call());
      } catch (err) {
        if (rethrow) throw err;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [applyState],
  );

  const add = useCallback(
    (kind: VocabularyKind, value: string, target = "") =>
      mutate(() => addVocabulary(kind, value, target), true),
    [mutate],
  );
  const remove = useCallback(
    (kind: VocabularyKind, value: string) => mutate(() => removeVocabulary(kind, value), false),
    [mutate],
  );
  const setHidden = useCallback(
    (kind: VocabularyKind, value: string, hidden: boolean) =>
      mutate(() => setVocabularyHidden(kind, value, hidden), false),
    [mutate],
  );
  const approveProposals = useCallback(
    (ids: string[], targets: Record<string, string> = {}) =>
      mutate(() => approveLibraryProposals(ids, targets), false),
    [mutate],
  );
  const rejectProposals = useCallback(
    (ids: string[]) => mutate(() => rejectLibraryProposals(ids), false),
    [mutate],
  );

  const generateProposals = useCallback(
    async (jdText?: string) => {
      setGenerating(true);
      setError(null);
      try {
        applyState(await generateLibraryProposals(jdText));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setGenerating(false);
      }
    },
    [applyState],
  );

  const value = useMemo(
    () => ({
      entries,
      effective,
      diagnostics,
      proposals,
      proposalWarning,
      loading,
      busy,
      generating,
      error,
      refresh,
      add,
      remove,
      setHidden,
      generateProposals,
      approveProposals,
      rejectProposals,
    }),
    [
      entries,
      effective,
      diagnostics,
      proposals,
      proposalWarning,
      loading,
      busy,
      generating,
      error,
      refresh,
      add,
      remove,
      setHidden,
      generateProposals,
      approveProposals,
      rejectProposals,
    ],
  );

  return <LibraryStateContext.Provider value={value}>{children}</LibraryStateContext.Provider>;
}

/** Access vocabulary state; throws if used outside LibraryProvider. */
export function useLibraryState(): LibraryStateValue {
  const ctx = useContext(LibraryStateContext);
  if (!ctx) {
    throw new Error("useLibraryState must be used within LibraryProvider");
  }
  return ctx;
}
