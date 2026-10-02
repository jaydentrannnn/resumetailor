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
  type CoverLetter,
  type Expansion,
  type JobSettings,
  type ProgressEvent,
  type RunHistoryEntry,
  type RunReport,
  type SkillsPlan,
  cancelJob,
  createJob,
  deleteRunHistory,
  fetchConfig,
  fetchJob,
  fetchResumeOutline,
  fetchRunHistory,
  fetchSettings,
  saveSettings,
  saveTargetField,
  triggerPdfDownload,
} from "../api";
import { DEFAULT_INCLUDE, DEFAULT_SETTINGS } from "./runDefaults";
import {
  LEGACY_SETTINGS_KEY,
  jdStorageKey,
  loadJdText,
  loadStoredJobId,
  isTerminalJobStatus,
  storeJobId,
  loadLegacySettings,
} from "./runStorage";
import { useWorkspaceState } from "./workspaceState";
import { emitAppEvent, onAppEvent } from "../lib/appEvents";

const SETTINGS_SAVE_DEBOUNCE_MS = 600;

type RunStateValue = {
  config: AppConfig | null;
  jdText: string;
  setJdText: (text: string) => void;
  settings: JobSettings;
  setSettings: (settings: JobSettings) => void;
  settingsLoaded: boolean;
  setTargetField: (field: string | null) => Promise<void>;
  settingsSaveState: "saved" | "unsaved" | "saving" | "failed";
  settingsSaveError: string | null;
  flushSettings: () => Promise<boolean>;
  discardSettings: () => Promise<void>;
  jobId: string | null;
  status: string | null;
  events: ProgressEvent[];
  report: RunReport | null;
  refreshReport: () => Promise<void>;
  expansion: Expansion | null;
  skills: SkillsPlan | null;
  coverLetter: CoverLetter | null;
  setCoverLetter: (letter: CoverLetter | null) => void;
  error: string | null;
  busy: boolean;
  queuePosition: number | null;
  history: RunHistoryEntry[];
  startJob: () => Promise<void>;
  cancelRun: () => Promise<void>;
  cancelling: boolean;
  refreshHistory: () => Promise<void>;
  /** Remove finished runs from history and clear results if the active view was deleted. */
  deleteHistoryRuns: (jobIds: string[]) => Promise<Record<string, string>>;
  /** Load a past (or still-running) job into the results tiles without re-downloading. */
  loadRun: (jobId: string) => Promise<void>;
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
  const [settingsSaveState, setSettingsSaveState] = useState<
    "saved" | "unsaved" | "saving" | "failed"
  >("saved");
  const [settingsSaveError, setSettingsSaveError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [report, setReport] = useState<RunReport | null>(null);
  const displayedJobId = useRef(jobId);
  displayedJobId.current = jobId;
  const [expansion, setExpansion] = useState<Expansion | null>(null);
  const [skills, setSkills] = useState<SkillsPlan | null>(null);
  const [coverLetter, setCoverLetter] = useState<CoverLetter | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [queuePosition, setQueuePosition] = useState<number | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [history, setHistory] = useState<RunHistoryEntry[]>([]);
  // Lives here (not RunPage) so remounting on Tailor ↔ Master tab switches
  // does not reset and re-trigger the post-success PDF download.
  const autoDownloadedFor = useRef<string | null>(null);
  const saveSettingsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const settingsRevision = useRef(0);
  const savedSettings = useRef<JobSettings>(DEFAULT_SETTINGS);
  const latestSettings = useRef<JobSettings>(DEFAULT_SETTINGS);
  const settingsWrite = useRef<Promise<void>>(Promise.resolve());
  const lastWriteFailed = useRef(false);
  const guidanceWrite = useRef<Promise<void>>(Promise.resolve());

  const setTargetField = useCallback((field: string | null): Promise<void> => {
    const write = guidanceWrite.current
      .catch(() => undefined)
      .then(async () => {
        setConfig(await saveTargetField(field));
      });
    guidanceWrite.current = write;
    return write;
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      setHistory(await fetchRunHistory());
    } catch {
      /* history is advisory — a failed fetch must not block the Tailor tab */
    }
  }, []);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

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

  const persistSettings = useCallback((next: JobSettings, revision: number): Promise<void> => {
    const write = settingsWrite.current
      .catch(() => undefined)
      .then(async () => {
        if (revision !== settingsRevision.current) return;
        setSettingsSaveState("saving");
        try {
          await saveSettings(next);
          if (next.model !== savedSettings.current.model) emitAppEvent("rt:setup-changed");
          savedSettings.current = next;
          lastWriteFailed.current = false;
          if (revision === settingsRevision.current) {
            setSettingsSaveState("saved");
            setSettingsSaveError(null);
          }
        } catch (err) {
          lastWriteFailed.current = true;
          if (revision === settingsRevision.current) {
            setSettingsSaveState("failed");
            setSettingsSaveError(err instanceof Error ? err.message : String(err));
          }
          throw err;
        }
      });
    settingsWrite.current = write;
    return write;
  }, []);

  const setSettings = useCallback(
    (next: JobSettings) => {
      latestSettings.current = next;
      setSettingsState(next);
      setSettingsSaveState("unsaved");
      setSettingsSaveError(null);
      const revision = ++settingsRevision.current;
      if (saveSettingsTimer.current) clearTimeout(saveSettingsTimer.current);
      saveSettingsTimer.current = setTimeout(() => {
        saveSettingsTimer.current = null;
        void persistSettings(next, revision).catch(() => undefined);
      }, SETTINGS_SAVE_DEBOUNCE_MS);
    },
    [persistSettings],
  );

  const flushSettings = useCallback(async (): Promise<boolean> => {
    try {
      await guidanceWrite.current;
    } catch {
      return false;
    }
    if (saveSettingsTimer.current) {
      clearTimeout(saveSettingsTimer.current);
      saveSettingsTimer.current = null;
    }
    try {
      await settingsWrite.current;
    } catch {
      /* retry the latest draft below */
    }
    if (latestSettings.current === savedSettings.current && !lastWriteFailed.current) return true;
    try {
      await persistSettings(latestSettings.current, settingsRevision.current);
      return true;
    } catch {
      return false;
    }
  }, [persistSettings]);

  const discardSettings = useCallback(async () => {
    if (saveSettingsTimer.current) clearTimeout(saveSettingsTimer.current);
    saveSettingsTimer.current = null;
    ++settingsRevision.current;
    try {
      await settingsWrite.current;
    } catch {
      /* failed write leaves the last saved value intact */
    }
    latestSettings.current = savedSettings.current;
    setSettingsState(savedSettings.current);
    lastWriteFailed.current = false;
    setSettingsSaveError(null);
    setSettingsSaveState("saved");
  }, []);

  useEffect(() => {
    // Cancel a pending debounced save on unmount (e.g. a profile switch remounts
    // this provider) so it cannot fire a PUT against a profile that is no longer active.
    return () => {
      if (saveSettingsTimer.current) clearTimeout(saveSettingsTimer.current);
    };
  }, []);

  useEffect(
    () =>
      // A template switch changes the page-fit numbers `/api/config` reports.
      onAppEvent("rt:template-changed", () => {
        fetchConfig()
          .then(setConfig)
          .catch(() => undefined); // keep the old numbers; the next visit reloads them
      }),
    [],
  );

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
          // the resume-derived config, same as a fresh session always has. GPA is
          // seeded from the resume's own current show_gpa (rather than the
          // all-included default) so this never silently reveals or hides it on the
          // first run.
          let gpa = DEFAULT_INCLUDE.gpa;
          try {
            const outline = await fetchResumeOutline();
            gpa = outline.gpa_currently_shown;
          } catch {
            /* outline fetch is best-effort here; fall back to the all-included default */
          }
          next = {
            ...DEFAULT_SETTINGS,
            pages: c.pages,
            experience: c.experience,
            projects: c.projects,
            model: c.model_profiles.includes(DEFAULT_SETTINGS.model)
              ? DEFAULT_SETTINGS.model
              : (c.model_profiles[0] ?? DEFAULT_SETTINGS.model),
            include: { ...DEFAULT_INCLUDE, gpa },
          };
        } else {
          next = res.settings;
        }

        setSettingsState(next);
        latestSettings.current = next;
        savedSettings.current = next;
        if (res.seeded) {
          // Persist the seeded/imported value so the next load already has it saved.
          lastWriteFailed.current = true;
          void persistSettings(next, settingsRevision.current).catch(() => undefined);
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
  }, [persistSettings]);

  useEffect(() => {
    /**
     * Re-attach to whatever job this profile last started, if any — a page reload
     * mid-run otherwise orphans the job server-side (it keeps executing with no UI
     * attached) and, once finished, its report/downloads become unreachable. A
     * restored *finished* job must not re-trigger the auto-download effect below,
     * so `autoDownloadedFor` is seeded before `report` is ever set.
     */
    const storedId = loadStoredJobId(activeId);
    if (!storedId) return;
    let cancelled = false;
    (async () => {
      try {
        const job = await fetchJob(storedId);
        if (cancelled) return;
        setJobId(storedId);
        setStatus(job.status);
        setEvents(job.events);
        setQueuePosition(job.queue_position);
        if (isTerminalJobStatus(job.status)) {
          autoDownloadedFor.current = storedId;
          setReport(job.report);
          setExpansion(job.expansion);
          setSkills(job.skills);
          setCoverLetter(job.cover_letter);
          setError(job.error);
        } else {
          setBusy(true);
        }
      } catch {
        // Job no longer exists server-side (process restarted, id stale) — drop it
        // rather than retrying against an id that will never resolve.
        storeJobId(activeId, null);
      }
    })();
    return () => {
      cancelled = true;
    };
    // `activeId` is fixed for the lifetime of any one mount of this provider (see
    // App.tsx's keying), so listing it here changes nothing behaviorally — it just
    // satisfies exhaustive-deps honestly instead of suppressing the warning.
  }, [activeId]);

  const pollUntilDone = useCallback(async (id: string) => {
    /** Poll job status until the run finishes, used when SSE is unavailable. */
    try {
      for (;;) {
        const job = await fetchJob(id);
        setStatus(job.status);
        setEvents(job.events);
        setQueuePosition(job.queue_position);
        if (isTerminalJobStatus(job.status)) {
          setReport(job.report);
          setExpansion(job.expansion);
          setSkills(job.skills);
          setCoverLetter(job.cover_letter);
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
        setSkills(job.skills);
        setCoverLetter(job.cover_letter);
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
    void refreshHistory();
  }, [jobId, report, status, refreshHistory]);

  useEffect(() => {
    if (status === "failed" || status === "cancelled") {
      void refreshHistory();
    }
  }, [status, refreshHistory]);

  const loadRun = useCallback(
    async (id: string) => {
      /** Surface a past run's report/preview without re-firing the auto-download. */
      try {
        const job = await fetchJob(id);
        // Seed before setting report — same guard the reload-reattach path uses.
        autoDownloadedFor.current = id;
        setJobId(id);
        storeJobId(activeId, id);
        setStatus(job.status);
        setEvents(job.events);
        setQueuePosition(job.queue_position);
        setReport(job.report);
        setExpansion(job.expansion);
        setSkills(job.skills);
        setCoverLetter(job.cover_letter);
        setError(job.error);
        setBusy(!isTerminalJobStatus(job.status));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [activeId],
  );

  const refreshReport = useCallback(async () => {
    if (!jobId) return;
    try {
      const job = await fetchJob(jobId);
      if (displayedJobId.current === jobId) setReport(job.report);
    } catch (err) {
      if (displayedJobId.current === jobId) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
  }, [jobId]);

  const clearDisplayedRun = useCallback(() => {
    /** Drop the results tiles when the run being viewed was removed from history. */
    setJobId(null);
    storeJobId(activeId, null);
    setStatus(null);
    setEvents([]);
    setReport(null);
    setExpansion(null);
    setSkills(null);
    setCoverLetter(null);
    setQueuePosition(null);
    setBusy(false);
    setError(null);
  }, [activeId]);

  const deleteHistoryRuns = useCallback(
    async (ids: string[]) => {
      const result = await deleteRunHistory(ids);
      if (jobId && result.deleted.includes(jobId) && !busy) {
        clearDisplayedRun();
      }
      await refreshHistory();
      return result.errors;
    },
    [jobId, busy, clearDisplayedRun, refreshHistory],
  );

  const startJob = useCallback(async () => {
    /** Enqueue a new run from the current JD text and settings. */
    if (!jdText.trim() || busy) return;
    setBusy(true);
    setError(null);
    setReport(null);
    setExpansion(null);
    setSkills(null);
    setCoverLetter(null);
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
    storeJobId(activeId, null);
    try {
      const { job_id, queue_position } = await createJob(jdText, settings);
      setJobId(job_id);
      storeJobId(activeId, job_id);
      setQueuePosition(queue_position);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }, [jdText, settings, busy, activeId]);

  useEffect(() => {
    // A finished run (whichever way it ended) always clears the "Cancelling…" flag,
    // including the case where cancellation itself is what finished it.
    if (!busy) setCancelling(false);
  }, [busy]);

  const cancelRun = useCallback(async () => {
    /** Ask the server to cancel the in-flight run. Cooperative: a queued job stops
     * immediately, a running one at its next pipeline-stage checkpoint — either way
     * the SSE stream (or the poll fallback) delivers the eventual "cancelled" status,
     * so this only needs to fire the request and reflect that it's in flight. */
    if (!jobId || !busy || cancelling) return;
    setCancelling(true);
    try {
      await cancelJob(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setCancelling(false);
    }
  }, [jobId, busy, cancelling]);

  const value = useMemo<RunStateValue>(
    () => ({
      config,
      jdText,
      setJdText,
      settings,
      setSettings,
      settingsLoaded,
      setTargetField,
      settingsSaveState,
      settingsSaveError,
      flushSettings,
      discardSettings,
      jobId,
      status,
      events,
      report,
      refreshReport,
      expansion,
      skills,
      coverLetter,
      setCoverLetter,
      error,
      busy,
      queuePosition,
      history,
      startJob,
      cancelRun,
      cancelling,
      refreshHistory,
      deleteHistoryRuns,
      loadRun,
    }),
    [
      config,
      jdText,
      setJdText,
      settings,
      setSettings,
      settingsLoaded,
      setTargetField,
      settingsSaveState,
      settingsSaveError,
      flushSettings,
      discardSettings,
      jobId,
      status,
      events,
      report,
      refreshReport,
      expansion,
      skills,
      coverLetter,
      setCoverLetter,
      error,
      busy,
      queuePosition,
      history,
      startJob,
      cancelRun,
      cancelling,
      refreshHistory,
      deleteHistoryRuns,
      loadRun,
    ],
  );

  return <RunStateContext.Provider value={value}>{children}</RunStateContext.Provider>;
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
