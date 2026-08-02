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
  type AppConfig,
  type Expansion,
  type JobSettings,
  type ProgressEvent,
  type RunReport,
  createJob,
  fetchConfig,
  fetchJob,
  triggerPdfDownload,
} from "../api";

const JD_KEY = "resumeTailor.jdText";
const SETTINGS_KEY = "resumeTailor.settings";

/** Defaults for a fresh Tailor session; also the merge base for persisted settings. */
export const DEFAULT_SETTINGS: JobSettings = {
  pages: 1,
  experience: null,
  projects: null,
  model: "claude",
  rewrite_model: null,
  expand_model: null,
  effort: null,
  no_semantic: false,
  no_widow_repair: false,
  no_verb_repair: false,
  merge: false,
  no_cache: false,
  no_expand: false,
  no_project_links: false,
  fill_target: null,
};

/**
 * Load a previously typed JD from localStorage, or an empty string.
 */
function loadJdText(): string {
  try {
    return localStorage.getItem(JD_KEY) ?? "";
  } catch {
    return "";
  }
}

/**
 * Load settings from localStorage merged over DEFAULT_SETTINGS so older blobs
 * missing newer fields (expand_model, no_expand, no_project_links, …) stay valid.
 */
function loadSettings(): JobSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<JobSettings>;
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

type RunStateValue = {
  config: AppConfig | null;
  jdText: string;
  setJdText: (text: string) => void;
  settings: JobSettings;
  setSettings: (settings: JobSettings) => void;
  jobId: string | null;
  status: string | null;
  events: ProgressEvent[];
  report: RunReport | null;
  expansion: Expansion | null;
  error: string | null;
  busy: boolean;
  queuePosition: number | null;
  startJob: () => Promise<void>;
};

const RunStateContext = createContext<RunStateValue | null>(null);

/**
 * Owns Tailor-page state above the router so tab switches and mid-run navigation
 * do not tear down the SSE stream or wipe JD text / settings / results.
 */
export function RunProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [jdText, setJdTextState] = useState(loadJdText);
  const [settings, setSettingsState] = useState<JobSettings>(loadSettings);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [report, setReport] = useState<RunReport | null>(null);
  const [expansion, setExpansion] = useState<Expansion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [queuePosition, setQueuePosition] = useState<number | null>(null);
  // Lives here (not RunPage) so remounting on Tailor ↔ Master tab switches
  // does not reset and re-trigger the post-success PDF download.
  const autoDownloadedFor = useRef<string | null>(null);

  const setJdText = useCallback((text: string) => {
    setJdTextState(text);
    try {
      localStorage.setItem(JD_KEY, text);
    } catch {
      /* quota / private mode — keep in-memory state */
    }
  }, []);

  const setSettings = useCallback((next: JobSettings) => {
    setSettingsState(next);
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
    } catch {
      /* quota / private mode — keep in-memory state */
    }
  }, []);

  useEffect(() => {
    fetchConfig()
      .then((c) => {
        setConfig(c);
        setSettingsState((s) => {
          // Only fill pages/experience/projects from the server when this is a
          // brand-new session (no prior persisted settings). A restored blob
          // already carries the user's last choices.
          const hadPersisted = (() => {
            try {
              return localStorage.getItem(SETTINGS_KEY) != null;
            } catch {
              return false;
            }
          })();
          const merged: JobSettings = hadPersisted
            ? {
                ...s,
                // Keep a valid profile if the saved one disappeared from the server list.
                model: c.model_profiles.includes(s.model)
                  ? s.model
                  : c.model_profiles.includes("claude")
                    ? "claude"
                    : (c.model_profiles[0] ?? "claude"),
              }
            : {
                ...s,
                pages: c.pages,
                experience: c.experience,
                projects: c.projects,
                model: c.model_profiles.includes("claude")
                  ? "claude"
                  : (c.model_profiles[0] ?? "claude"),
              };
          try {
            localStorage.setItem(SETTINGS_KEY, JSON.stringify(merged));
          } catch {
            /* ignore */
          }
          return merged;
        });
      })
      .catch((err: Error) => {
        setError(err.message);
      });
  }, []);

  const pollUntilDone = useCallback(async (id: string) => {
    /** Poll job status until the run finishes, used when SSE is unavailable. */
    try {
      for (;;) {
        const job = await fetchJob(id);
        setStatus(job.status);
        setEvents(job.events);
        setQueuePosition(job.queue_position);
        if (job.status === "succeeded" || job.status === "failed") {
          setReport(job.report);
          setExpansion(job.expansion);
          setError(job.error);
          setBusy(false);
          return;
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!jobId || !busy) return;

    const source = new EventSource(`/api/jobs/${jobId}/events`);
    source.onmessage = (msg) => {
      const event = JSON.parse(msg.data) as ProgressEvent;
      setEvents((prev) => [...prev, event]);
    };
    source.addEventListener("done", async () => {
      source.close();
      try {
        const job = await fetchJob(jobId);
        setStatus(job.status);
        setReport(job.report);
        setExpansion(job.expansion);
        setError(job.error);
        if (job.events.length) setEvents(job.events);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    });
    source.onerror = () => {
      source.close();
      void pollUntilDone(jobId);
    };
    return () => source.close();
  }, [jobId, busy, pollUntilDone]);

  useEffect(() => {
    if (!jobId || !report || status !== "succeeded") return;
    if (autoDownloadedFor.current === jobId) return;
    autoDownloadedFor.current = jobId;
    void triggerPdfDownload(jobId);
  }, [jobId, report, status]);

  const startJob = useCallback(async () => {
    /** Enqueue a new run from the current JD text and settings. */
    if (!jdText.trim() || busy) return;
    setBusy(true);
    setError(null);
    setReport(null);
    setExpansion(null);
    setEvents([]);
    setStatus("queued");
    try {
      const { job_id, queue_position } = await createJob(jdText, settings);
      setJobId(job_id);
      setQueuePosition(queue_position);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }, [jdText, settings, busy]);

  const value = useMemo<RunStateValue>(
    () => ({
      config,
      jdText,
      setJdText,
      settings,
      setSettings,
      jobId,
      status,
      events,
      report,
      expansion,
      error,
      busy,
      queuePosition,
      startJob,
    }),
    [
      config,
      jdText,
      setJdText,
      settings,
      setSettings,
      jobId,
      status,
      events,
      report,
      expansion,
      error,
      busy,
      queuePosition,
      startJob,
    ],
  );

  return (
    <RunStateContext.Provider value={value}>{children}</RunStateContext.Provider>
  );
}

/**
 * Access Tailor-page state. Must be used under `RunProvider`.
 */
export function useRunState(): RunStateValue {
  const ctx = useContext(RunStateContext);
  if (!ctx) {
    throw new Error("useRunState must be used within RunProvider");
  }
  return ctx;
}
