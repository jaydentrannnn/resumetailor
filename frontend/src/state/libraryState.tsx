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
  type LibraryAliasImpact,
  type LibraryEffective,
  type LibraryOverrides,
  type LibraryPackDraft,
  type LibraryPackSummary,
  type LibraryProposal,
  type LibraryState,
  approveLibraryProposals,
  createLibraryPack,
  deleteLibraryPack,
  fetchLibraries,
  generateLibraryProposals,
  previewLibraryImpact,
  rejectLibraryProposals,
  setLibrarySelection,
  updateLibraryPack,
} from "../api";

const EMPTY_OVERRIDES: LibraryOverrides = {
  tag_aliases: {},
  tag_aliases_removed: [],
  verb_families: {},
  verb_families_removed: [],
};

const EMPTY_EFFECTIVE: LibraryEffective = {
  tag_alias_count: 0,
  verb_count: 0,
  fingerprint: "",
};

type LibraryStateValue = {
  packs: LibraryPackSummary[];
  enabledPacks: string[];
  overrides: LibraryOverrides;
  effective: LibraryEffective;
  diagnostics: string[];
  proposals: LibraryProposal[];
  /** Set only after a `generateProposals` call that partially failed. */
  proposalWarning: string | null;
  loading: boolean;
  /** True while any mutation (pack write/delete, selection change, approve/reject) is
   * in flight — disables the whole Settings panel so a second edit can't race the
   * first. */
  busy: boolean;
  /** True specifically while a proposal-generation call is in flight — surfaced
   * separately from `busy` because that call can run for a while and the "Generate
   * suggestions" button wants its own spinner rather than disabling everything. */
  generating: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setEnabled: (ids: string[]) => Promise<void>;
  setOverrides: (next: LibraryOverrides) => Promise<void>;
  /** `id === null` creates a new pack; otherwise updates the existing one. */
  savePack: (id: string | null, draft: LibraryPackDraft) => Promise<void>;
  deletePack: (id: string) => Promise<void>;
  previewImpact: (tagAliases: Record<string, string>) => Promise<LibraryAliasImpact[]>;
  generateProposals: (jdText?: string) => Promise<void>;
  /** Throws `LibraryApprovalConflict` (409) when the change would rewrite an existing
   * tag and `acknowledgeRewrites` was not set — the caller shows the impact and
   * re-calls with it set, rather than this hook swallowing the distinction. */
  approveProposals: (
    ids: string[],
    targetPackId: string,
    acknowledgeRewrites: boolean,
  ) => Promise<void>;
  rejectProposals: (ids: string[]) => Promise<void>;
};

const LibraryStateContext = createContext<LibraryStateValue | null>(null);

/**
 * Owns the active profile's vocabulary-library state (packs, selection, overrides,
 * pending proposals) for the Settings tab. Keyed on the active workspace id in
 * `App.tsx` like its siblings — a profile switch unmounts/remounts this provider
 * rather than resetting it in place.
 */
export function LibraryProvider({ children }: { children: ReactNode }) {
  const [packs, setPacks] = useState<LibraryPackSummary[]>([]);
  const [enabledPacks, setEnabledPacks] = useState<string[]>([]);
  const [overrides, setOverridesState] = useState<LibraryOverrides>(EMPTY_OVERRIDES);
  const [effective, setEffective] = useState<LibraryEffective>(EMPTY_EFFECTIVE);
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [proposals, setProposals] = useState<LibraryProposal[]>([]);
  const [proposalWarning, setProposalWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyState = useCallback((next: LibraryState) => {
    setPacks(next.packs);
    setEnabledPacks(next.enabled_packs);
    setOverridesState(next.overrides);
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

  const updateSelection = useCallback(
    async (nextEnabled: string[], nextOverrides: LibraryOverrides) => {
      setBusy(true);
      setError(null);
      try {
        applyState(await setLibrarySelection(nextEnabled, nextOverrides));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [applyState],
  );

  const setEnabled = useCallback(
    (ids: string[]) => updateSelection(ids, overrides),
    [updateSelection, overrides],
  );

  const setOverrides = useCallback(
    (next: LibraryOverrides) => updateSelection(enabledPacks, next),
    [updateSelection, enabledPacks],
  );

  const savePack = useCallback(
    async (id: string | null, draft: LibraryPackDraft) => {
      setBusy(true);
      setError(null);
      try {
        const next = id === null
          ? await createLibraryPack(draft)
          : await updateLibraryPack(id, draft);
        applyState(next);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        throw err; // let the caller keep its edit form open on failure
      } finally {
        setBusy(false);
      }
    },
    [applyState],
  );

  const deletePack = useCallback(
    async (id: string) => {
      setBusy(true);
      setError(null);
      try {
        applyState(await deleteLibraryPack(id));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [applyState],
  );

  const previewImpact = useCallback(
    async (tagAliases: Record<string, string>) => {
      const res = await previewLibraryImpact(tagAliases);
      return res.impacts;
    },
    [],
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

  const approveProposals = useCallback(
    async (ids: string[], targetPackId: string, acknowledgeRewrites: boolean) => {
      setBusy(true);
      setError(null);
      try {
        applyState(await approveLibraryProposals(ids, targetPackId, acknowledgeRewrites));
      } catch (err) {
        // Do not fold LibraryApprovalConflict into `error` — the caller (SettingsPage)
        // catches it specifically to show the impact and offer to re-confirm.
        if (!(err instanceof Error) || err.name !== "LibraryApprovalConflict") {
          setError(err instanceof Error ? err.message : String(err));
        }
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [applyState],
  );

  const rejectProposals = useCallback(
    async (ids: string[]) => {
      setBusy(true);
      setError(null);
      try {
        applyState(await rejectLibraryProposals(ids));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [applyState],
  );

  const value = useMemo(
    () => ({
      packs,
      enabledPacks,
      overrides,
      effective,
      diagnostics,
      proposals,
      proposalWarning,
      loading,
      busy,
      generating,
      error,
      refresh,
      setEnabled,
      setOverrides,
      savePack,
      deletePack,
      previewImpact,
      generateProposals,
      approveProposals,
      rejectProposals,
    }),
    [
      packs,
      enabledPacks,
      overrides,
      effective,
      diagnostics,
      proposals,
      proposalWarning,
      loading,
      busy,
      generating,
      error,
      refresh,
      setEnabled,
      setOverrides,
      savePack,
      deletePack,
      previewImpact,
      generateProposals,
      approveProposals,
      rejectProposals,
    ],
  );

  return (
    <LibraryStateContext.Provider value={value}>{children}</LibraryStateContext.Provider>
  );
}

/**
 * Access Settings-tab library state; throws if used outside LibraryProvider.
 */
export function useLibraryState(): LibraryStateValue {
  const ctx = useContext(LibraryStateContext);
  if (!ctx) {
    throw new Error("useLibraryState must be used within LibraryProvider");
  }
  return ctx;
}
