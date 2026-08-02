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
  type TemplateBuildResponse,
  type TemplateInfo,
  fetchTemplateInfo,
  uploadTemplate,
} from "../api";

type TemplateStateValue = {
  info: TemplateInfo | null;
  loading: boolean;
  uploading: boolean;
  error: string | null;
  buildLog: string | null;
  lastBuildOk: boolean | null;
  /** Cache-buster so the iframe reloads after a successful rebuild. */
  previewKey: number;
  refresh: () => Promise<void>;
  upload: (file: File) => Promise<void>;
};

const TemplateStateContext = createContext<TemplateStateValue | null>(null);

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

  const refresh = useCallback(async () => {
    /** Reload template metadata from the API. */
    setLoading(true);
    setError(null);
    try {
      const next = await fetchTemplateInfo();
      setInfo(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const upload = useCallback(async (file: File) => {
    /** Replace the baseline, rebuild the tagged template, and refresh metadata. */
    setUploading(true);
    setError(null);
    setBuildLog(null);
    setLastBuildOk(null);
    try {
      const result: TemplateBuildResponse = await uploadTemplate(file);
      setBuildLog(result.log || null);
      setLastBuildOk(true);
      if (result.info) {
        setInfo(result.info);
      } else {
        await refresh();
      }
      // Bust the iframe cache so the new template is visible immediately.
      setPreviewKey((k) => k + 1);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setBuildLog(message);
      setLastBuildOk(false);
    } finally {
      setUploading(false);
    }
  }, [refresh]);

  const value = useMemo(
    () => ({
      info,
      loading,
      uploading,
      error,
      buildLog,
      lastBuildOk,
      previewKey,
      refresh,
      upload,
    }),
    [
      info,
      loading,
      uploading,
      error,
      buildLog,
      lastBuildOk,
      previewKey,
      refresh,
      upload,
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
