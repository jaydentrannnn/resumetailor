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
  type AppConfig,
  fetchConfig,
  fetchMasterResume,
  saveMasterResume,
  validateMasterResume,
} from "../api";
import {
  type MasterResume,
  completenessErrors,
} from "../lib/resumeEdit";

type EditorStateValue = {
  resume: MasterResume | null;
  setResume: (resume: MasterResume) => void;
  config: AppConfig | null;
  errors: string[];
  message: string | null;
  busy: boolean;
  validate: () => Promise<void>;
  save: () => Promise<void>;
};

const EditorStateContext = createContext<EditorStateValue | null>(null);

/**
 * Owns Master-resume editor state above the router so unsaved draft edits survive
 * a switch to the Tailor tab. Deliberately in-memory only — persisting a draft
 * across reloads risks shadowing what is on disk.
 */
export function EditorProvider({ children }: { children: ReactNode }) {
  const [resume, setResume] = useState<MasterResume | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (loaded) return;
    Promise.all([fetchMasterResume(), fetchConfig()])
      .then(([raw, cfg]) => {
        setResume(raw as MasterResume);
        setConfig(cfg);
        setLoaded(true);
      })
      .catch((err: Error) => {
        setErrors([err.message]);
        setLoaded(true);
      });
  }, [loaded]);

  const validate = useCallback(async () => {
    /** Dry-run validation against local completeness rules then the API. */
    if (!resume) return;
    setBusy(true);
    setMessage(null);
    try {
      const local = completenessErrors(resume);
      if (local.length) {
        setErrors(local);
        return;
      }
      const result = await validateMasterResume(
        resume as unknown as Record<string, unknown>,
      );
      setErrors(result.errors);
      if (result.ok && result.summary) {
        setMessage(
          `Valid — ${result.summary.bullets} bullets, ${result.summary.tags} tags`,
        );
      }
    } catch (err) {
      setErrors([err instanceof Error ? err.message : String(err)]);
    } finally {
      setBusy(false);
    }
  }, [resume]);

  const save = useCallback(async () => {
    /** Persist the draft and reload so tags come back canonicalised. */
    if (!resume) return;
    setBusy(true);
    setMessage(null);
    try {
      const local = completenessErrors(resume);
      if (local.length) {
        setErrors(local);
        return;
      }
      const result = await saveMasterResume(
        resume as unknown as Record<string, unknown>,
      );
      setErrors(result.errors);
      if (result.ok && result.summary) {
        setMessage(
          `Saved — ${result.summary.name}: ${result.summary.bullets} bullets (previous file backed up)`,
        );
        const fresh = (await fetchMasterResume()) as MasterResume;
        setResume(fresh);
        const cfg = await fetchConfig();
        setConfig(cfg);
      }
    } catch (err) {
      setErrors([err instanceof Error ? err.message : String(err)]);
    } finally {
      setBusy(false);
    }
  }, [resume]);

  const value = useMemo<EditorStateValue>(
    () => ({
      resume,
      setResume,
      config,
      errors,
      message,
      busy,
      validate,
      save,
    }),
    [resume, config, errors, message, busy, validate, save],
  );

  return (
    <EditorStateContext.Provider value={value}>
      {children}
    </EditorStateContext.Provider>
  );
}

/**
 * Access Master-resume editor state. Must be used under `EditorProvider`.
 */
export function useEditorState(): EditorStateValue {
  const ctx = useContext(EditorStateContext);
  if (!ctx) {
    throw new Error("useEditorState must be used within EditorProvider");
  }
  return ctx;
}
