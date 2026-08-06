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
  type TemplateAnalyzeResponse,
  type TemplateBuildResponse,
  type TemplateHeadingKind,
  type TemplateInfo,
  type TemplateLibraryEntry,
  activateTemplateLibrary,
  analyzeTemplate,
  deleteTemplateLibrary,
  fetchTemplateInfo,
  fetchTemplateLibrary,
  remapTemplateHeadings,
  renameTemplateLibrary,
  uploadTemplate,
} from "../api";

export type WizardStep =
  | "idle"
  | "analyzing"
  | "mapping"
  | "installing"
  | "done"
  | "error";

type TemplateStateValue = {
  info: TemplateInfo | null;
  loading: boolean;
  uploading: boolean;
  error: string | null;
  buildLog: string | null;
  lastBuildOk: boolean | null;
  /** Cache-buster so the iframe reloads after a successful rebuild. */
  previewKey: number;
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
  refresh: () => Promise<void>;
  refreshLibrary: () => Promise<void>;
  beginAnalyze: (file: File) => Promise<void>;
  setProfileDraft: (profile: Record<string, unknown> | null) => void;
  confirmInstall: () => Promise<boolean>;
  resetWizard: () => void;
  activateLibraryEntry: (id: string) => Promise<void>;
  renameLibraryEntry: (id: string, label: string) => Promise<void>;
  deleteLibraryEntry: (id: string) => Promise<void>;
};

const TemplateStateContext = createContext<TemplateStateValue | null>(null);

/**
 * Derive a default install label from an upload filename stem.
 */
function labelFromFilename(name: string): string {
  const stem = name.replace(/\.docx$/i, "").trim() || "Untitled";
  return stem.replace(/[\s_]+/g, " ").trim().slice(0, 80);
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
  const [wizardStep, setWizardStep] = useState<WizardStep>("idle");
  const [draftFile, setDraftFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<TemplateAnalyzeResponse | null>(null);
  const [profileDraft, setProfileDraft] = useState<Record<string, unknown> | null>(
    null,
  );
  const [headingOverrides, setHeadingOverrides] = useState<
    Record<number, TemplateHeadingKind>
  >({});
  const [remapBusy, setRemapBusy] = useState(false);
  const [calibrateAlso, setCalibrateAlso] = useState(true);
  const [installLabel, setInstallLabel] = useState("");
  const [library, setLibrary] = useState<TemplateLibraryEntry[]>([]);
  const [libraryActiveId, setLibraryActiveId] = useState<string | null>(null);
  const [libraryBusy, setLibraryBusy] = useState(false);

  const refreshLibrary = useCallback(async () => {
    /** Reload the named template library list. */
    try {
      const next = await fetchTemplateLibrary();
      setLibrary(next.entries);
      setLibraryActiveId(next.active_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const refresh = useCallback(async () => {
    /** Reload template metadata and library from the API, and re-fetch the preview. */
    setLoading(true);
    setError(null);
    try {
      const next = await fetchTemplateInfo();
      setInfo(next);
      await refreshLibrary();
      // Bump the cache-buster too: the iframe src is `preview.pdf?v=${previewKey}`, so
      // without this Refresh only updated the metadata card and the browser re-showed
      // the PDF it already had — which is what made a master-resume edit look like it
      // had not applied.
      setPreviewKey((k) => k + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [refreshLibrary]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const resetWizard = useCallback(() => {
    /** Clear in-memory wizard state without touching the installed template. */
    setWizardStep("idle");
    setDraftFile(null);
    setAnalysis(null);
    setProfileDraft(null);
    setHeadingOverrides({});
    setInstallLabel("");
    setError(null);
    setBuildLog(null);
    setLastBuildOk(null);
  }, []);

  const beginAnalyze = useCallback(async (file: File) => {
    /** Run preflight analysis and open the mapping step when possible. */
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
      const result = await analyzeTemplate(file);
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
      const result: TemplateBuildResponse = await uploadTemplate(
        draftFile,
        profileDraft,
        { calibrate: calibrateAlso, label: installLabel.trim() || undefined },
      );
      setBuildLog(result.log || null);
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
  }, [draftFile, profileDraft, calibrateAlso, installLabel, refresh, refreshLibrary]);

  const activateLibraryEntry = useCallback(
    async (id: string) => {
      /** Switch the live slot to a saved library snapshot. */
      setLibraryBusy(true);
      setError(null);
      try {
        const result = await activateTemplateLibrary(id, {
          calibrate: calibrateAlso,
        });
        setBuildLog(result.log || null);
        if (result.info) {
          setInfo(result.info);
        } else {
          await refresh();
        }
        await refreshLibrary();
        setPreviewKey((k) => k + 1);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLibraryBusy(false);
      }
    },
    [calibrateAlso, refresh, refreshLibrary],
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

  const deleteLibraryEntry = useCallback(
    async (id: string) => {
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
    },
    [],
  );

  const value = useMemo(
    () => ({
      info,
      loading,
      uploading,
      error,
      buildLog,
      lastBuildOk,
      previewKey,
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
      refresh,
      refreshLibrary,
      beginAnalyze,
      setProfileDraft,
      confirmInstall,
      resetWizard,
      activateLibraryEntry,
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
      refresh,
      refreshLibrary,
      beginAnalyze,
      confirmInstall,
      resetWizard,
      activateLibraryEntry,
      renameLibraryEntry,
      deleteLibraryEntry,
    ],
  );

  return (
    <TemplateStateContext.Provider value={value}>{children}</TemplateStateContext.Provider>
  );
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
