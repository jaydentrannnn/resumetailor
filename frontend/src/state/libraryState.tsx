import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
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
  resetLibraryPack,
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
  overridesDraft: LibraryOverrides;
  overridesSaveState: "saved" | "unsaved" | "saving" | "failed";
  editOverrides: (patch: Partial<LibraryOverrides>) => void;
  flushOverrides: () => Promise<boolean>;
  discardOverrides: () => Promise<void>;
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
  resetPack: (id: string) => Promise<void>;
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
  const [overridesDraft, setOverridesDraft] = useState<LibraryOverrides>(EMPTY_OVERRIDES);
  const [overridesSaveState, setOverridesSaveState] = useState<
    "saved" | "unsaved" | "saving" | "failed"
  >("saved");
  const overridesDraftRef = useRef<LibraryOverrides>(EMPTY_OVERRIDES);
  const savedOverridesRef = useRef<LibraryOverrides>(EMPTY_OVERRIDES);
  const overridesRevision = useRef(0);
  const overridesTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const overridesWrite = useRef<Promise<void>>(Promise.resolve());
  const overridesDirty = useRef(false);
  const [effective, setEffective] = useState<LibraryEffective>(EMPTY_EFFECTIVE);
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [proposals, setProposals] = useState<LibraryProposal[]>([]);
  const [proposalWarning, setProposalWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectionRevision = useRef(0);
  const selectionWrites = useRef<Promise<void>>(Promise.resolve());

  const applyState = useCallback((next: LibraryState) => {
    setPacks(next.packs);
    setEnabledPacks(next.enabled_packs);
    setOverridesState(next.overrides);
    savedOverridesRef.current = next.overrides;
    if (!overridesDirty.current) {
      overridesDraftRef.current = next.overrides;
      setOverridesDraft(next.overrides);
    }
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
      const revision = ++selectionRevision.current;
      setBusy(true);
      setError(null);
      try {
        const write = selectionWrites.current.then(() =>
          setLibrarySelection(nextEnabled, nextOverrides),
        );
        selectionWrites.current = write.then(
          () => {},
          () => {},
        );
        const result = await write;
        if (revision === selectionRevision.current) applyState(result);
      } catch (err) {
        if (revision === selectionRevision.current)
          setError(err instanceof Error ? err.message : String(err));
        throw err;
      } finally {
        if (revision === selectionRevision.current) setBusy(false);
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

  const flushOverrides = useCallback(async (): Promise<boolean> => {
    if (overridesTimer.current) clearTimeout(overridesTimer.current);
    overridesTimer.current = null;
    try {
      await overridesWrite.current;
    } catch {
      /* retry the current draft */
    }
    if (!overridesDirty.current) return true;
    const revision = overridesRevision.current;
    const draft = overridesDraftRef.current;
    setOverridesSaveState("saving");
    const write = setOverrides(draft);
    overridesWrite.current = write;
    try {
      await write;
      if (revision === overridesRevision.current) {
        overridesDirty.current = false;
        setOverridesSaveState("saved");
      }
      return revision === overridesRevision.current;
    } catch {
      if (revision === overridesRevision.current) setOverridesSaveState("failed");
      return false;
    }
  }, [setOverrides]);

  const editOverrides = useCallback(
    (patch: Partial<LibraryOverrides>) => {
      const next = { ...overridesDraftRef.current, ...patch };
      overridesDraftRef.current = next;
      overridesDirty.current = true;
      ++overridesRevision.current;
      setOverridesDraft(next);
      setOverridesSaveState("unsaved");
      if (overridesTimer.current) clearTimeout(overridesTimer.current);
      overridesTimer.current = setTimeout(() => {
        overridesTimer.current = null;
        void flushOverrides();
      }, 600);
    },
    [flushOverrides],
  );

  const discardOverrides = useCallback(async () => {
    if (overridesTimer.current) clearTimeout(overridesTimer.current);
    overridesTimer.current = null;
    ++overridesRevision.current;
    try {
      await overridesWrite.current;
    } catch {
      /* keep last server state */
    }
    overridesDirty.current = false;
    overridesDraftRef.current = savedOverridesRef.current;
    setOverridesDraft(savedOverridesRef.current);
    setOverridesSaveState("saved");
  }, []);

  useEffect(
    () => () => {
      if (overridesTimer.current) clearTimeout(overridesTimer.current);
    },
    [],
  );

  const savePack = useCallback(
    async (id: string | null, draft: LibraryPackDraft) => {
      setBusy(true);
      setError(null);
      // No catch here, deliberately: on failure this rethrows to the caller (the pack
      // editor, which shows the failure itself and stays open) without also setting
      // the provider-level `error` — that would print the same message twice, once in
      // the Packs banner and once in the editor.
      try {
        const next =
          id === null ? await createLibraryPack(draft) : await updateLibraryPack(id, draft);
        applyState(next);
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

  const resetPack = useCallback(
    async (id: string) => {
      setBusy(true);
      setError(null);
      try {
        applyState(await resetLibraryPack(id));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [applyState],
  );

  const previewImpact = useCallback(async (tagAliases: Record<string, string>) => {
    const res = await previewLibraryImpact(tagAliases);
    return res.impacts;
  }, []);

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
      overridesDraft,
      overridesSaveState,
      editOverrides,
      flushOverrides,
      discardOverrides,
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
      resetPack,
      previewImpact,
      generateProposals,
      approveProposals,
      rejectProposals,
    }),
    [
      packs,
      enabledPacks,
      overrides,
      overridesDraft,
      overridesSaveState,
      editOverrides,
      flushOverrides,
      discardOverrides,
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
      resetPack,
      previewImpact,
      generateProposals,
      approveProposals,
      rejectProposals,
    ],
  );

  return <LibraryStateContext.Provider value={value}>{children}</LibraryStateContext.Provider>;
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
