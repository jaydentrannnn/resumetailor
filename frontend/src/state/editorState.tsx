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
  setResume: (
    resume: MasterResume | ((prev: MasterResume) => MasterResume),
  ) => void;
  config: AppConfig | null;
  errors: string[];
  message: string | null;
  busy: boolean;
  /** True when the draft differs from what was last loaded or saved. */
  dirty: boolean;
  validate: () => Promise<void>;
  save: () => Promise<void>;
  /** Replace the working draft with `resume` (e.g. a template-wizard import),
   * intentionally leaving the saved snapshot untouched so `dirty` immediately
   * reflects that this draft has not been saved to disk. */
  loadDraft: (resume: MasterResume, message?: string) => void;
  /** Adopt `resume` as both the working draft AND the saved snapshot — for a resume
   * that was already written to disk by the caller (e.g. the template wizard's
   * merge-and-save action), so it must never read as an unsaved draft. */
  syncFromDisk: (resume: MasterResume, message?: string) => void;
};

const EditorStateContext = createContext<EditorStateValue | null>(null);

/**
 * Owns Master-resume editor state above the router so unsaved draft edits survive
 * a switch to the Tailor tab. Deliberately in-memory only — persisting a draft
 * across reloads risks shadowing what is on disk.
 */
export function EditorProvider({ children }: { children: ReactNode }) {
  const [resume, setResumeState] = useState<MasterResume | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  // Snapshot of the resume as last loaded or saved, so `dirty` reflects genuinely
  // unsaved edits rather than "a resume is loaded at all".
  const [savedSnapshot, setSavedSnapshot] = useState<string | null>(null);

  const setResume = useCallback(
    (next: MasterResume | ((prev: MasterResume) => MasterResume)) => {
      /**
       * Support functional updates so chained edits in one event (e.g. bullet
       * tags + vocabulary) do not clobber each other with a stale snapshot.
       */
      setResumeState((prev) => {
        if (!prev) return prev;
        return typeof next === "function" ? next(prev) : next;
      });
    },
    [],
  );

  useEffect(() => {
    if (loaded) return;
    Promise.all([fetchMasterResume(), fetchConfig()])
      .then(([raw, cfg]) => {
        const record = raw as Record<string, unknown>;
        if (!Array.isArray(record.sections)) {
          // The backend now always returns a `sections`-shaped resume (see
          // `web/app.py::get_master_resume`); a payload without it means a stale
          // frontend build talking to a newer backend (or vice versa) — fail loudly
          // rather than rendering an editor with no sections to show.
          throw new Error(
            "Master resume response is missing `sections` — the app build is out of " +
              "date with the server. Reload the page; if that doesn't help, rebuild " +
              "the frontend.",
          );
        }
        setResumeState(raw as MasterResume);
        setSavedSnapshot(JSON.stringify(raw));
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
        setResumeState(fresh);
        setSavedSnapshot(JSON.stringify(fresh));
        const cfg = await fetchConfig();
        setConfig(cfg);
      }
    } catch (err) {
      setErrors([err instanceof Error ? err.message : String(err)]);
    } finally {
      setBusy(false);
    }
  }, [resume]);

  const dirty = useMemo(
    () => resume != null && savedSnapshot != null && JSON.stringify(resume) !== savedSnapshot,
    [resume, savedSnapshot],
  );

  const loadDraft = useCallback((next: MasterResume, draftMessage?: string) => {
    setResumeState(next);
    setErrors([]);
    setMessage(draftMessage ?? "Imported draft loaded — review and save to keep it.");
  }, []);

  const syncFromDisk = useCallback((next: MasterResume, syncMessage?: string) => {
    setResumeState(next);
    setSavedSnapshot(JSON.stringify(next));
    setErrors([]);
    setMessage(syncMessage ?? "Master resume updated.");
  }, []);

  const value = useMemo<EditorStateValue>(
    () => ({
      resume,
      setResume,
      config,
      errors,
      message,
      busy,
      dirty,
      validate,
      save,
      loadDraft,
      syncFromDisk,
    }),
    [resume, setResume, config, errors, message, busy, dirty, validate, save, loadDraft, syncFromDisk],
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
