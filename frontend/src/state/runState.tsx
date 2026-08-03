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
  fetchSettings,
  saveSettings,
  triggerPdfDownload,
} from "../api";
import { useWorkspaceState } from "./workspaceState";

const JD_KEY_PREFIX = "resumeTailor.jdText";
//: Pre-server-settings storage key. Settings now live in the active profile's
//: settings.json; this is only read once, to import a leftover blob on first load.
const LEGACY_SETTINGS_KEY = "resumeTailor.settings";
const SETTINGS_SAVE_DEBOUNCE_MS = 600;

/** Defaults for a fresh Tailor session; also the merge base for settings from the server. */
export const DEFAULT_SETTINGS: JobSettings = {
  pages: 1,
  experience: null,
  projects: null,
  // Ollama, not Claude: a fresh install should run without an Anthropic key. Keep this in
  // step with `JobSettings.model`'s server-side default — the seeding branch below reads
  // this value rather than repeating the name.
  model: "ollama",
  /** null keeps the server's OLLAMA_MODEL (gemma4:cloud); only a typed value overrides. */
  ollama_model: null,
  /** null keeps the server's GEMINI_MODEL; only a typed value overrides. */
  gemini_model: null,
  rewrite_model: null,
  expand_model: null,
  effort: null,
  no_semantic: false,
  no_widow_repair: false,
  no_verb_repair: false,
  merge: false,
  no_cache: false,
  no_expand: false,
  no_facets: false,
  no_project_links: false,
  fill_target: null,
};

/**
 * A JD draft is scoped per profile — different profiles target different postings —
 * but stays client-side scratch rather than server state, since it is never final
 * until a run is started.
 */
function jdStorageKey(workspaceId: string | null): string {
  return workspaceId ? `${JD_KEY_PREFIX}:${workspaceId}` : JD_KEY_PREFIX;
}

/**
 * Load a previously typed JD from localStorage for this profile, or an empty string.
 */
function loadJdText(workspaceId: string | null): string {
  try {
    return localStorage.getItem(jdStorageKey(workspaceId)) ?? "";
  } catch {
    return "";
  }
}

/**
 * Read a settings blob left over from before settings moved server-side. Consulted
 * exactly once, by the settings-loading effect below, to avoid losing a returning
 * user's choices the first time their profile's settings.json is created.
 */
function loadLegacySettings(): Partial<JobSettings> | null {
  try {
    const raw = localStorage.getItem(LEGACY_SETTINGS_KEY);
    return raw ? (JSON.parse(raw) as Partial<JobSettings>) : null;
  } catch {
    return null;
  }
}

type RunStateValue = {
  config: AppConfig | null;
  jdText: string;
  setJdText: (text: string) => void;
  settings: JobSettings;
  setSettings: (settings: JobSettings) => void;
  settingsLoaded: boolean;
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
  // `RunProvider` is remounted (keyed) on a profile switch — see App.tsx — so
  // `activeId` is fixed for the lifetime of any one mount of this component.
  const { activeId } = useWorkspaceState();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [jdText, setJdTextState] = useState(() => loadJdText(activeId));
  const [settings, setSettingsState] = useState<JobSettings>(DEFAULT_SETTINGS);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
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
  const saveSettingsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setJdText = useCallback(
    (text: string) => {
      setJdTextState(text);
      try {
        localStorage.setItem(jdStorageKey(activeId), text);
      } catch {
        /* quota / private mode — keep in-memory state */
      }
    },
    [activeId],
  );

  const setSettings = useCallback((next: JobSettings) => {
    setSettingsState(next);
    if (saveSettingsTimer.current) clearTimeout(saveSettingsTimer.current);
    // Debounced so dragging the fill-target slider or ticking several toggles in a
    // row does not fire a PUT per change — only once settings stop changing.
    saveSettingsTimer.current = setTimeout(() => {
      void saveSettings(next).catch(() => {
        /* best-effort persistence; the in-memory value is still correct for this run */
      });
    }, SETTINGS_SAVE_DEBOUNCE_MS);
  }, []);

  useEffect(() => {
    // Cancel a pending debounced save on unmount (e.g. a profile switch remounts
    // this provider) so it cannot fire a PUT against a profile that is no longer active.
    return () => {
      if (saveSettingsTimer.current) clearTimeout(saveSettingsTimer.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const c = await fetchConfig();
        if (cancelled) return;
        setConfig(c);

        const res = await fetchSettings();
        if (cancelled) return;

        const legacy = loadLegacySettings();
        let next: JobSettings;
        if (res.seeded && legacy) {
          // This profile has never saved settings, and this browser has a blob from
          // before settings moved server-side: import it once rather than losing it.
          next = { ...DEFAULT_SETTINGS, ...legacy };
        } else if (res.seeded) {
          // Brand-new profile with nothing to import: seed run-size defaults from
          // the resume-derived config, same as a fresh session always has.
          next = {
            ...DEFAULT_SETTINGS,
            pages: c.pages,
            experience: c.experience,
            projects: c.projects,
            model: c.model_profiles.includes(DEFAULT_SETTINGS.model)
              ? DEFAULT_SETTINGS.model
              : (c.model_profiles[0] ?? DEFAULT_SETTINGS.model),
          };
        } else {
          next = res.settings;
        }

        setSettingsState(next);
        if (res.seeded) {
          // Persist the seeded/imported value so the next load already has it saved.
          void saveSettings(next).catch(() => undefined);
        }
        try {
          localStorage.removeItem(LEGACY_SETTINGS_KEY);
        } catch {
          /* ignore */
        }
        setSettingsLoaded(true);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setSettingsLoaded(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
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
    setQueuePosition(null);
    setStatus("queued");
    // Drop the finished run's id *before* awaiting `createJob`. Without this the SSE
    // effect below re-fires on (previous jobId, busy=true) and subscribes to the job
    // that already finished: the server replays that job's whole event list and then
    // sends `done`, which refills the progress tile with the previous run's events,
    // restores its report, and sets `busy` false — so the new job, once its id
    // arrives, is never subscribed to at all and runs invisibly.
    setJobId(null);
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
      settingsLoaded,
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
      settingsLoaded,
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
