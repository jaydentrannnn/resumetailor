import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useRef,
  type ReactNode,
} from "react";
import {
  type DefaultTemplate,
  type TemplateAnalyzeResponse,
  type TemplateBuildResponse,
  type TemplateHeadingKind,
  type TemplateInfo,
  type TemplateLibraryEntry,
  type TemplateSnapshot,
  activateTemplateLibrary,
  analyzeTemplate,
  buildLogWithTitles,
  deleteTemplateLibrary,
  fetchTemplateSnapshot,
  installDefaultTemplate,
  remapTemplateHeadings,
  renameTemplateLibrary,
  revertTemplateLibraryToFixed,
  uploadTemplate,
} from "../api";
import { emitAppEvent } from "../lib/appEvents";
import { useToast } from "../lib/toast";

export type WizardStep = "idle" | "analyzing" | "mapping" | "installing" | "done" | "error";

type TemplateStateValue = {
  info: TemplateInfo | null;
  loading: boolean;
  uploading: boolean;
  error: string | null;
  buildLog: string | null;
  lastBuildOk: boolean | null;
  /** Cache-buster so the iframe reloads after a successful rebuild. */
  previewKey: number;
  previewRevision: string | null;
  pendingTemplate: string | null;
  wizardStep: WizardStep;
  draftFile: File | null;
  analysis: TemplateAnalyzeResponse | null;
  profileDraft: Record<string, unknown> | null;
  /** Accumulated user-confirmed heading reassignments, keyed by paragraph id, sent
   * with every remap call so a second override never loses the first. */
  headingOverrides: Record<number, TemplateHeadingKind>;
  remapBusy: boolean;
  remapHeading: (paragraphId: number, kind: TemplateHeadingKind) => Promise<void>;
  /** When true, install also measures fit constants (Word/LibreOffice; slower). */
  calibrateAlso: boolean;
  setCalibrateAlso: (value: boolean) => void;
  /** Library label for the next install (defaults from filename). */
  installLabel: string;
  setInstallLabel: (value: string) => void;
  library: TemplateLibraryEntry[];
  libraryActiveId: string | null;
  libraryBusy: boolean;
  /** Built-in starter templates, each marked when already saved or in use. */
  defaults: DefaultTemplate[];
  /** Install (or re-activate) a starter template; true on success. */
  installDefault: (name: string) => Promise<boolean>;
  refresh: () => Promise<void>;
  refreshLibrary: () => Promise<void>;
  /** Re-analyze with `convertBullets` to turn typed bullets into a real list. */
  beginAnalyze: (file: File, options?: { convertBullets?: boolean }) => Promise<void>;
  setProfileDraft: (profile: Record<string, unknown> | null) => void;
  confirmInstall: () => Promise<boolean>;
  resetWizard: () => void;
  activateLibraryEntry: (id: string) => Promise<void>;
  /** Restore the fixed layout of a template switched to movable sections. */
  revertLibraryEntry: (id: string) => Promise<void>;
  renameLibraryEntry: (id: string, label: string) => Promise<void>;
  deleteLibraryEntry: (id: string) => Promise<void>;
};

const TemplateStateContext = createContext<TemplateStateValue | null>(null);

/**
 * Derive a default install label from an upload filename stem.
 */
function labelFromFilename(name: string): string {
  const stem = name.replace(/\.docx$/i, "").trim() || "Untitled";
  return stem
    .replace(/[\s_]+/g, " ")
    .trim()
    .slice(0, 80);
}

/**
 * Owns Template-tab state above the router so a slow rebuild (Word ~9s) survives
 * switching away to Tailor / Master resume and back.
 */
export function TemplateProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<TemplateInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [buildLog, setBuildLog] = useState<string | null>(null);
  const [lastBuildOk, setLastBuildOk] = useState<boolean | null>(null);
  const [previewKey, setPreviewKey] = useState(0);
  const [previewRevision, setPreviewRevision] = useState<string | null>(null);
  const [pendingTemplate, setPendingTemplate] = useState<string | null>(null);
  const sequence = useRef(0);
  const switching = useRef(false);
  const [wizardStep, setWizardStep] = useState<WizardStep>("idle");
  const [draftFile, setDraftFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<TemplateAnalyzeResponse | null>(null);
  const [profileDraft, setProfileDraft] = useState<Record<string, unknown> | null>(null);
  const [headingOverrides, setHeadingOverrides] = useState<Record<number, TemplateHeadingKind>>({});
  const [remapBusy, setRemapBusy] = useState(false);
  const [calibrateAlso, setCalibrateAlso] = useState(true);
  const [installLabel, setInstallLabel] = useState("");
  const [convertBullets, setConvertBullets] = useState(false);
  const [library, setLibrary] = useState<TemplateLibraryEntry[]>([]);
  const [libraryActiveId, setLibraryActiveId] = useState<string | null>(null);
  const [libraryBusy, setLibraryBusy] = useState(false);
  const [defaults, setDefaults] = useState<DefaultTemplate[]>([]);
  const toast = useToast();

  const refreshLibrary = useCallback(async () => {
    if (switching.current) return;
    const token = ++sequence.current;
    try {
      const next = await fetchTemplateSnapshot();
      if (token !== sequence.current) return;
      applySnapshot(next);
    } catch (err) {
      if (token !== sequence.current) return;
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      toast.error("Couldn't reload your templates", message);
    }
  }, [toast]);

  function applySnapshot(next: TemplateSnapshot) {
    setInfo(next.info);
    setLibrary(next.library.entries);
    setLibraryActiveId(next.library.active_id);
    setDefaults(next.defaults);
    setPreviewRevision(next.preview_revision);
    setPreviewKey((k) => k + 1);
  }

  const refresh = useCallback(async () => {
    if (switching.current) return;
    const token = ++sequence.current;
    setLoading(true);
    setError(null);
    try {
      const next = await fetchTemplateSnapshot();
      if (token === sequence.current) applySnapshot(next);
    } catch (err) {
      if (token === sequence.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (token === sequence.current) setLoading(false);
    }
  }, []);

  const afterSwitch = useCallback(async (token: number, snapshot?: TemplateSnapshot | null) => {
    try {
      const next = snapshot ?? (await fetchTemplateSnapshot());
      if (token !== sequence.current) return;
      applySnapshot(next);
      emitAppEvent("rt:template-changed");
    } catch (err) {
      if (token !== sequence.current) return;
      setPreviewRevision(null);
      setError(`Couldn't synchronize template state: ${String(err)}`);
    } finally {
      if (token === sequence.current) {
        switching.current = false;
        setPendingTemplate(null);
        setLibraryBusy(false);
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
    const requestSequence = sequence;
    return () => {
      requestSequence.current++;
    };
  }, [refresh]);

  const resetWizard = useCallback(() => {
    /** Clear in-memory wizard state without touching the installed template. */
    setWizardStep("idle");
    setDraftFile(null);
    setAnalysis(null);
    setProfileDraft(null);
    setHeadingOverrides({});
    setInstallLabel("");
    setConvertBullets(false);
    setError(null);
    setBuildLog(null);
    setLastBuildOk(null);
  }, []);

  const beginAnalyze = useCallback(async (file: File, options?: { convertBullets?: boolean }) => {
    /** Run preflight analysis and open the mapping step when possible. */
    const convert = Boolean(options?.convertBullets);
    setConvertBullets(convert);
    setUploading(true);
    setError(null);
    setBuildLog(null);
    setLastBuildOk(null);
    setDraftFile(file);
    setInstallLabel(labelFromFilename(file.name));
    setWizardStep("analyzing");
    setAnalysis(null);
    setProfileDraft(null);
    setHeadingOverrides({});
    try {
      const result = await analyzeTemplate(file, { convertBullets: convert });
      setAnalysis(result);
      setProfileDraft(result.suggested_profile);
      setWizardStep("mapping");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setWizardStep("error");
    } finally {
      setUploading(false);
    }
  }, []);

  const remapHeading = useCallback(
    async (paragraphId: number, kind: TemplateHeadingKind) => {
      /** Confirm/reassign one heading's kind; a real server round trip since it can
       * change entry splitting, field reconciliation, and date detection elsewhere. */
      if (!analysis) return;
      const nextOverrides = { ...headingOverrides, [paragraphId]: kind };
      setRemapBusy(true);
      setError(null);
      try {
        const result = await remapTemplateHeadings(analysis.source_sha256, nextOverrides);
        setHeadingOverrides(nextOverrides);
        setAnalysis(result);
        setProfileDraft(result.suggested_profile);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setRemapBusy(false);
      }
    },
    [analysis, headingOverrides],
  );

  const confirmInstall = useCallback(async (): Promise<boolean> => {
    /** Install the retained File with the confirmed profile draft. Returns whether
     * the install succeeded, so a caller chaining a follow-up action (e.g. "also
     * import content") never has to read back a state variable that a stale closure
     * or React's batching could make out of date. */
    if (!draftFile || !profileDraft) {
      setError("Choose a file and confirm the mapping before installing.");
      setWizardStep("error");
      return false;
    }
    setUploading(true);
    setError(null);
    setBuildLog(null);
    setLastBuildOk(null);
    setWizardStep("installing");
    try {
      const result: TemplateBuildResponse = await uploadTemplate(draftFile, profileDraft, {
        calibrate: calibrateAlso,
        label: installLabel.trim() || undefined,
        convertBullets,
      });
      setBuildLog(buildLogWithTitles(result));
      setLastBuildOk(true);
      if (result.info) {
        setInfo(result.info);
      } else {
        await refresh();
      }
      await refreshLibrary();
      setPreviewKey((k) => k + 1);
      setWizardStep("done");
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setBuildLog(message);
      setLastBuildOk(false);
      setWizardStep("error");
      return false;
    } finally {
      setUploading(false);
    }
  }, [
    draftFile,
    profileDraft,
    calibrateAlso,
    installLabel,
    convertBullets,
    refresh,
    refreshLibrary,
  ]);

  const activateLibraryEntry = useCallback(
    async (id: string) => {
      /** Switch the live slot to a saved library snapshot. */
      if (switching.current) return;
      switching.current = true;
      const token = ++sequence.current;
      setPendingTemplate(library.find((entry) => entry.id === id)?.label ?? id);
      setLibraryBusy(true);
      setError(null);
      let snapshot: TemplateSnapshot | null | undefined;
      try {
        const result = await activateTemplateLibrary(id, {
          calibrate: false,
        });
        if (token !== sequence.current) return;
        snapshot = result.snapshot;
        setBuildLog(result.log || null);
      } catch (err) {
        if (token === sequence.current) setError(err instanceof Error ? err.message : String(err));
      } finally {
        // Always: a request that failed late (page-fit tuning, a timeout) may already
        // have switched the template, and the badge must follow the server.
        await afterSwitch(token, snapshot);
      }
    },
    [library, afterSwitch],
  );

  const revertLibraryEntry = useCallback(
    async (id: string) => {
      /** Restore a saved template's fixed layout (switching live when it is in use). */
      if (switching.current) return;
      switching.current = true;
      const token = ++sequence.current;
      setPendingTemplate(library.find((entry) => entry.id === id)?.label ?? id);
      setLibraryBusy(true);
      setError(null);
      let snapshot: TemplateSnapshot | null | undefined;
      try {
        const result = await revertTemplateLibraryToFixed(id);
        if (token !== sequence.current) return;
        snapshot = result.snapshot;
        setBuildLog(result.log || null);
      } catch (err) {
        if (token === sequence.current) setError(err instanceof Error ? err.message : String(err));
      } finally {
        await afterSwitch(token, snapshot);
      }
    },
    [library, afterSwitch],
  );

  const installDefault = useCallback(
    async (name: string): Promise<boolean> => {
      /** Build and install a starter template, or re-activate its saved copy. */
      if (switching.current) return false;
      switching.current = true;
      const token = ++sequence.current;
      setPendingTemplate(defaults.find((entry) => entry.name === name)?.label ?? name);
      setLibraryBusy(true);
      setError(null);
      let snapshot: TemplateSnapshot | null | undefined;
      try {
        const result = await installDefaultTemplate(name, { calibrate: false });
        if (token !== sequence.current) return false;
        snapshot = result.snapshot;
        setBuildLog(buildLogWithTitles(result));
        return true;
      } catch (err) {
        if (token === sequence.current) setError(err instanceof Error ? err.message : String(err));
        return false;
      } finally {
        await afterSwitch(token, snapshot);
      }
    },
    [defaults, afterSwitch],
  );

  const renameLibraryEntry = useCallback(
    async (id: string, label: string) => {
      /** Rename a saved template; refresh the list from the response. */
      setLibraryBusy(true);
      setError(null);
      try {
        const next = await renameTemplateLibrary(id, label);
        setLibrary(next.entries);
        setLibraryActiveId(next.active_id);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLibraryBusy(false);
      }
    },
    [refresh],
  );

  const deleteLibraryEntry = useCallback(async (id: string) => {
    /** Remove a non-active library entry. */
    setLibraryBusy(true);
    setError(null);
    try {
      const next = await deleteTemplateLibrary(id);
      setLibrary(next.entries);
      setLibraryActiveId(next.active_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLibraryBusy(false);
    }
  }, []);

  const value = useMemo(
    () => ({
      info,
      loading,
      uploading,
      error,
      buildLog,
      lastBuildOk,
      previewKey,
      previewRevision,
      pendingTemplate,
      wizardStep,
      draftFile,
      analysis,
      profileDraft,
      headingOverrides,
      remapBusy,
      remapHeading,
      calibrateAlso,
      setCalibrateAlso,
      installLabel,
      setInstallLabel,
      library,
      libraryActiveId,
      libraryBusy,
      defaults,
      installDefault,
      refresh,
      refreshLibrary,
      beginAnalyze,
      setProfileDraft,
      confirmInstall,
      resetWizard,
      activateLibraryEntry,
      revertLibraryEntry,
      renameLibraryEntry,
      deleteLibraryEntry,
    }),
    [
      info,
      loading,
      uploading,
      error,
      buildLog,
      lastBuildOk,
      previewKey,
      previewRevision,
      pendingTemplate,
      wizardStep,
      draftFile,
      analysis,
      profileDraft,
      headingOverrides,
      remapBusy,
      remapHeading,
      calibrateAlso,
      installLabel,
      library,
      libraryActiveId,
      libraryBusy,
      defaults,
      installDefault,
      refresh,
      refreshLibrary,
      beginAnalyze,
      confirmInstall,
      resetWizard,
      activateLibraryEntry,
      revertLibraryEntry,
      renameLibraryEntry,
      deleteLibraryEntry,
    ],
  );

  return <TemplateStateContext.Provider value={value}>{children}</TemplateStateContext.Provider>;
}

/**
 * Access Template-tab state; throws if used outside TemplateProvider.
 */
export function useTemplateState(): TemplateStateValue {
  const ctx = useContext(TemplateStateContext);
  if (!ctx) {
    throw new Error("useTemplateState must be used within TemplateProvider");
  }
  return ctx;
}
