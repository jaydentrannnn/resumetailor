import { useCallback, useEffect, useRef, useState } from "react";
import { EDGE_DEBUG_COMMAND } from "../lib/browserCommand";
import {
  type ApplicantProfile,
  type ApplyOperation,
  type ApplicationRow,
  type ApplicationsList,
  type BrowserStatus,
  type DailyStatus,
  type Packet,
  applicationsExportUrl,
  getApplicantProfile,
  getApplication,
  getApplyOperation,
  getBrowserStatus,
  focusApplicationReviewTab,
  refreshApplicationReview,
  correctApplicationField,
  getDailyStatus,
  listApplyOperations,
  listApplications,
  putApplicantProfile,
  retryApplication,
  startApplyOperation,
  setApplicationStatus,
  controlApplyOperation,
} from "../api";
import { useRunState } from "../state/runState";
import { ApplicationReview } from "../components/ApplicationReview";
import { isTerminalRow, retryLabel, retryTitle } from "../lib/applicationRows";
import { tailorModelLabel } from "../lib/modelLabel";

const STATUS_CHIPS = [
  "ready",
  "awaiting_review",
  "awaiting_otp",
  "fill_failed",
  "submit_unconfirmed",
  "screened_out",
  "needs_browser",
  "tailoring",
  "submitted",
  "discovered",
] as const;

//: Deliberately narrower than the backend's `preparation._FILLABLE`: bulk Fill only
//: takes `ready` rows so a test batch never fills every row. `awaiting_review`,
//: `awaiting_otp` and `fill_failed` rows go through the per-row Continue/Reopen buttons.
const FILLABLE_STATUSES = new Set([
  "ready",
]);

/** Summary counters worth showing live, in funnel order. */
const PROGRESS_COUNTERS = [
  ["total_candidates", "candidates"],
  ["new_rows", "new"],
  ["discovered", "discovered"],
  ["jd_fetched", "jd fetched"],
  ["prefiltered_out", "prefiltered"],
  ["screened_out", "screened out"],
  ["grouped", "grouped"],
  ["reused", "reused"],
  ["tailored", "tailored"],
  ["ready", "ready"],
  ["needs_browser", "needs browser"],
  ["tailor_failed", "tailor failed"],
  ["submitted", "submitted"],
  ["submit_failed", "submit failed"],
] as const;

/** How often to re-poll `/api/applications/daily-status` while a run is live. */
const POLL_MS = 2000;

/**
 * Percent complete for the processing phase, clamped to 0-100.
 *
 * `total` is 0 during discovery (the row count is not known until every source
 * has been fetched), which reads as 0% rather than a divide-by-zero.
 */
export function runProgressPercent(processed: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0;
  const pct = Math.round((processed / total) * 100);
  return Math.max(0, Math.min(100, pct));
}

export function applicationStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: "Ready",
    tailoring: "Preparing",
    submitted: "Submitted",
    discovered: "Discovered",
    needs_browser: "Browser needed",
    awaiting_review: "Needs review",
    awaiting_otp: "Verification code needed",
    fill_failed: "Fill failed",
    tailor_failed: "Preparation failed",
    submit_unconfirmed: "Submission unconfirmed",
    screened_out: "Screened out",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

/** Human-readable one-liner for the current phase of a daily pass. */
export function describePhase(status: DailyStatus | null): string {
  if (!status) return "";
  if (status.running) {
    if (status.phase === "discovering") {
      return status.source_id
        ? `Fetching source ${status.source_id}…`
        : "Fetching sources…";
    }
    if (status.phase === "processing") {
      const position = Math.min(status.processed + 1, Math.max(status.total, 1));
      const action = status.fetch_only ? "Recording" : "Processing";
      return status.current
        ? `${action} ${position}/${status.total}: ${status.current}`
        : `${action} ${position}/${status.total}…`;
    }
    return "Starting…";
  }
  if (status.phase === "done") {
    const reason = (status.summary?.reason as string) || "";
    if (reason) return `Last run skipped: ${reason}`;
    const modeDesc = status.fetch_only ? " (fetch only)" : status.dry_run ? " (dry run)" : "";
    return `Last run finished${modeDesc}`;
  }
  return "Idle";
}

/**
 * Daily apply funnel: queue of discovered/ready applications, CDP status,
 * packet drawer, and applicant-profile editor.
 */
export function ApplicationsPage() {
  const { settings, setSettings, config } = useRunState();
  const [list, setList] = useState<ApplicationsList | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [page, setPage] = useState(0);
  const [browser, setBrowser] = useState<BrowserStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [packet, setPacket] = useState<Packet | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedApplication, setSelectedApplication] = useState<ApplicationRow | null>(null);
  const [profile, setProfile] = useState<ApplicantProfile | null>(null);
  const [workdayPasswordSet, setWorkdayPasswordSet] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileDirty, setProfileDirty] = useState(false);
  const profileDirtyRef = useRef(false);
  const [daily, setDaily] = useState<DailyStatus | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [limit, setLimit] = useState<string>("");
  const [commandCopied, setCommandCopied] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const listRequestId = useRef(0);
  const [operation, setOperation] = useState<ApplyOperation | null>(null);
  const [checkingBrowser, setCheckingBrowser] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [clockNow, setClockNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setClockNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);

  const operationActive = operation != null && ["queued", "running", "paused"].includes(operation.state);

  // Close overflow menu when clicking outside
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if ((e.target as HTMLElement).closest?.("[data-actions-menu]")) return;
      setOpenMenuId(null);
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  // Restore and poll the active Apply operation independently from legacy daily runs.
  useEffect(() => {
    let cancelled = false;
    let operationId = operation?.operation_id ?? "";
    async function tick() {
      try {
        if (!operationId) {
          const recent = await listApplyOperations();
          const active = recent.find((item) => ["queued", "running", "paused"].includes(item.state));
          if (active) operationId = active.operation_id;
          else if (recent[0]) setOperation(recent[0]);
        }
        if (!operationId) return;
        const next = await getApplyOperation(operationId);
        if (cancelled) return;
        setOperation(next);
        await refreshListRef.current();
        if (!["queued", "running", "paused"].includes(next.state)) operationId = "";
      } catch {
        /* Retain the last known operation rather than erasing useful progress. */
      }
    }
    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [operation?.operation_id]);

  const checkBrowser = useCallback(async () => {
    setCheckingBrowser(true);
    try {
      const status = await getBrowserStatus();
      setBrowser(status);
    } catch {
      /* network or request error */
    } finally {
      setCheckingBrowser(false);
    }
  }, []);

  // Automatically probe CDP status every 5 seconds while offline so launching the browser updates it immediately
  useEffect(() => {
    if (browser?.reachable) return;
    const timer = setInterval(() => {
      getBrowserStatus().then(setBrowser).catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [browser?.reachable]);

  const refresh = useCallback(async () => {
    const requestId = ++listRequestId.current;
    const [apps, status, prof] = await Promise.all([
      listApplications({ status: filter || undefined, limit: 50, offset: page * 50 }),
      getBrowserStatus(),
      getApplicantProfile(),
    ]);
    if (requestId === listRequestId.current) setList(apps);
    setBrowser(status);
    if (!profileDirtyRef.current) {
      setProfile(prof.profile);
      setWorkdayPasswordSet(prof.workday_password_set);
    }
  }, [filter, page]);

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, [refresh]);

  /** Re-fetch only the queue table — used by the poll loop, which must stay cheap. */
  const refreshList = useCallback(async () => {
    const requestId = ++listRequestId.current;
    const apps = await listApplications({ status: filter || undefined, limit: 50, offset: page * 50 });
    if (requestId === listRequestId.current) setList(apps);
  }, [filter, page]);

  const refreshListRef = useRef(refreshList);
  refreshListRef.current = refreshList;
  // A tailor retry returns at once with the row at `tailoring`; keep the table polling
  // until it settles so the row flips to ready / tailor failed without a manual reload.
  const hasTailoringRowRef = useRef(false);
  hasTailoringRowRef.current = (list?.applications ?? []).some((row) => row.status === "tailoring");

  // Polls progress even when idle, so a run started elsewhere (the nightly
  // scheduler, the CLI, another tab) still shows up here. The table is only
  // re-fetched while a run is live, on the running -> finished edge, or while a
  // retried row is still tailoring.
  useEffect(() => {
    let cancelled = false;
    let wasRunning = false;

    async function tick() {
      try {
        const status = await getDailyStatus();
        if (cancelled) return;
        setDaily(status);
        if (status.running || wasRunning || hasTailoringRowRef.current) {
          await refreshListRef.current();
        }
        wasRunning = status.running;
      } catch {
        /* a failed poll is not worth a page-level error banner */
      }
    }

    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const counts = list?.counts ?? {};
  const rows = list?.applications ?? [];
  const totalPages = Math.max(1, Math.ceil((list?.total ?? 0) / 50));
  useEffect(() => {
    if (list && page >= totalPages) setPage(totalPages - 1);
  }, [list, page, totalPages]);
  function changePage(nextPage: number) {
    listRequestId.current += 1;
    setSelectedIds(new Set());
    setList(null);
    setPage(nextPage);
  }
  function changeFilter(nextFilter: string) {
    listRequestId.current += 1;
    setSelectedIds(new Set());
    setList(null);
    setPage(0);
    setFilter(nextFilter);
  }
  const prepareSelectedIds = rows
    .filter((row) => selectedIds.has(row.source_job_id) && !isTerminalRow(row))
    .map((row) => row.source_job_id);
  const fillSelectedIds = rows
    .filter((row) => selectedIds.has(row.source_job_id) && FILLABLE_STATUSES.has(row.status) && row.preparation_eligible !== false)
    .map((row) => row.source_job_id);
  const selectedPreparationReasons = rows
    .filter((row) => selectedIds.has(row.source_job_id) && !row.preparation_eligible)
    .flatMap((row) => row.preparation_reasons ?? []);

  async function onStartStage(action: "find" | "prepare" | "fill", ids?: string[], fillMode: "initial" | "continue" | "reopen" = "initial", forcePrepare = false) {
    setBusy(true);
    setError(null);
    try {
      const parsed = Number.parseInt(limit, 10);
      const started = await startApplyOperation({
        action,
        fill_mode: fillMode,
        force_prepare: forcePrepare,
        application_ids: ids ?? [],
        limit: Number.isFinite(parsed) && parsed > 0 ? parsed : null,
        dry_run: action === "find" && dryRun,
        auto_submit: settings.apply.auto_submit_enabled,
        blocker_mode: "continue",
        model_provider: settings.apply.model_provider,
        model_name: settings.apply.model_name,
      });
      setOperation(started);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function toggleSelected(sourceJobId: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(sourceJobId)) next.delete(sourceJobId);
      else next.add(sourceJobId);
      return next;
    });
  }

  const browserCmd = EDGE_DEBUG_COMMAND;

  /** Persist the unattended batch-submit cap, clamped and debounced like any other setting. */
  function onSubmitCapChange(raw: string) {
    if (raw.trim() === "") return;
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    const clamped = Math.min(500, Math.max(0, Math.round(n)));
    setSettings({
      ...settings,
      apply: { ...settings.apply, auto_submit_max_per_run: clamped },
    });
  }

  /** Persist the autofill model (Fill's written answers and choice resolution) —
   * separate from the Tailor model settings, which Prepare's tailoring and screening
   * use; see `ApplySettings.model_spec` / `daily._job_settings` on the backend. */
  function onModelProviderChange(provider: string) {
    setSettings({
      ...settings,
      apply: {
        ...settings.apply,
        model_provider: provider as typeof settings.apply.model_provider,
      },
    });
  }

  function onModelNameChange(name: string) {
    setSettings({ ...settings, apply: { ...settings.apply, model_name: name } });
  }

  /** Copy the Edge launch command so the user can paste-and-run instead of
   * hand-selecting the code block. The server (often a Docker container) has no
   * way to spawn a process on the host, so this is the closest a browser button
   * can get to "launch it" — see the Desktop shortcut for true one-click. */
  async function onCopyBrowserCommand() {
    try {
      await navigator.clipboard.writeText(browserCmd);
      setCommandCopied(true);
      setTimeout(() => setCommandCopied(false), 2000);
    } catch {
      /* clipboard API unavailable (insecure context, permission denied, …) —
       * the command is still visible/selectable in the code block below. */
    }
  }

  async function onOpenPacket(row: ApplicationRow) {
    setSelectedId(row.source_job_id);
    setError(null);
    try {
      const detail = await getApplication(row.source_job_id);
      setPacket(detail.packet);
      setSelectedApplication(detail.application);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onFill(row: ApplicationRow) {
    await onStartStage("fill", [row.source_job_id], row.fill?.browser_target_id ? "continue" : "initial");
  }

  async function onReviewResults(row: ApplicationRow) {
    setSelectedId(row.source_job_id);
    setSelectedApplication(row);
    setPacket(null);
    setError(null);
    requestAnimationFrame(() => document.getElementById("apply-review-results")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  async function onReviewTab(row: ApplicationRow) {
    setError(null);
    try { await focusApplicationReviewTab(row.source_job_id); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  async function onRefreshReview(row: ApplicationRow) {
    setError(null);
    try { setOperation(await refreshApplicationReview(row.source_job_id)); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  async function onCorrectField(
    field: NonNullable<NonNullable<ApplicationRow["fill"]>["review_fields"]>[number],
    value: string | null,
    optionIds: string[],
  ) {
    if (!selectedApplication?.fill?.review_snapshot_id) return;
    setError(null);
    try {
      setOperation(await correctApplicationField(selectedApplication.source_job_id, {
        snapshot_id: selectedApplication.fill.review_snapshot_id,
        field_id: field.field_id,
        expected_state_hash: field.expected_state_hash,
        value,
        option_ids: optionIds,
        idempotency_key: crypto.randomUUID(),
      }));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  const reviewOperationId = operation?.operation_id;
  const reviewOperationAction = operation?.action;
  const reviewOperationState = operation?.state;
  useEffect(() => {
    if (!selectedId || !reviewOperationId || !["inspect", "correct"].includes(reviewOperationAction || "") || ["queued", "running", "paused"].includes(reviewOperationState || "")) return;
    getApplication(selectedId).then((detail) => setSelectedApplication(detail.application)).catch(() => {});
  }, [reviewOperationId, reviewOperationAction, reviewOperationState, selectedId]);

  async function onRetry(row: ApplicationRow) {
    setBusy(true);
    setError(null);
    try {
      await retryApplication(row.source_job_id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onMark(row: ApplicationRow, status: string) {
    setError(null);
    try {
      await setApplicationStatus(row.source_job_id, status);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onSaveProfile() {
    if (!profile) return;
    setBusy(true);
    try {
      const saved = await putApplicantProfile(profile);
      setProfile(saved.profile);
      setWorkdayPasswordSet(saved.workday_password_set);
      profileDirtyRef.current = false;
      setProfileDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-ink">Applications</h1>
          <p className="text-sm text-ink-muted">
            Find jobs, prepare tailored files, then fill selected applications with visible progress.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                browser?.reachable
                  ? "bg-accent-soft text-ink"
                  : "bg-danger/10 text-danger"
              }`}
              title={browser?.error || browser?.cdp_url}
            >
              Browser CDP {browser?.reachable ? "reachable" : "offline"}
            </span>
            <button
              type="button"
              onClick={() => void checkBrowser()}
              disabled={checkingBrowser}
              title="Re-check host browser CDP connection"
              className="rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink-muted hover:text-ink disabled:opacity-50"
            >
              {checkingBrowser ? "Checking…" : "↻ Check"}
            </button>
          </div>
          <label
            className="flex items-center gap-1.5 text-xs text-ink-muted"
            title="Record discoveries only — no JD fetch, no tailoring, nothing written to the queue."
          >
            <input
              type="checkbox"
              checked={dryRun}
              disabled={daily?.running}
              onChange={(e) => setDryRun(e.target.checked)}
            />
            Dry run
          </label>
          <label
            className="flex items-center gap-1.5 text-xs text-ink-muted"
            title="Cap how many newly discovered postings this pass processes. Blank uses the profile's max_new_per_day."
          >
            Limit
            <input
              type="number"
              min={1}
              max={500}
              value={limit}
              disabled={daily?.running}
              placeholder="all"
              onChange={(e) => setLimit(e.target.value)}
              className="w-16 rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink"
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-ink-muted" title="Maximum verified submissions in one Fill operation.">
            Auto-submit cap
            <input
              type="number"
              min={0}
              max={500}
              value={settings.apply.auto_submit_max_per_run}
              onChange={(e) => onSubmitCapChange(e.target.value)}
              className="w-16 rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink"
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs font-medium text-ink">
            <input
              type="checkbox"
              checked={settings.apply.auto_submit_enabled}
              onChange={(e) => setSettings({
                ...settings,
                apply: {
                  ...settings.apply,
                  auto_submit_enabled: e.target.checked,
                  auto_submit_max_per_run:
                    e.target.checked && settings.apply.auto_submit_max_per_run === 0
                      ? 1
                      : settings.apply.auto_submit_max_per_run,
                },
              })}
            />
            Auto-submit verified forms
          </label>
          <span
            className="text-xs text-ink-muted"
            title="Prepare tailors and screens with the Tailor tab's model settings. Change them on the Tailor tab."
          >
            Tailoring: {tailorModelLabel(settings, config)} (Tailor tab)
          </span>
          <label
            className="flex items-center gap-1.5 text-xs text-ink-muted"
            title="Model for written answers and choice resolution during Fill. Prepare's tailoring uses the Tailor tab's model settings."
          >
            Autofill model
            <select
              value={settings.apply.model_provider}
              onChange={(e) => onModelProviderChange(e.target.value)}
              className="rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink"
            >
              <option value="ollama">ollama</option>
              <option value="lmstudio">lmstudio</option>
              <option value="gemini">gemini</option>
              <option value="anthropic">anthropic</option>
            </select>
            <input
              type="text"
              value={settings.apply.model_name}
              onChange={(e) => onModelNameChange(e.target.value)}
              placeholder="model name"
              className="w-40 rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink"
            />
          </label>
          <a
            className="rounded-md border border-line px-3 py-1.5 text-sm text-ink"
            href={applicationsExportUrl()}
          >
            Export CSV
          </a>
        </div>
      </div>

      <section className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel p-3">
        <button
          type="button"
          className="rounded-md border border-line bg-bg px-3 py-2 text-sm font-medium text-ink disabled:opacity-50"
          disabled={busy || operationActive}
          onClick={() => void onStartStage("find")}
        >
          1. Find jobs
        </button>
        <button
          type="button"
          className="rounded-md border border-accent/50 bg-accent-soft px-3 py-2 text-sm font-medium text-ink disabled:opacity-50"
          disabled={busy || operationActive || prepareSelectedIds.length === 0}
          onClick={() => void onStartStage("prepare", prepareSelectedIds)}
        >
          2. Prepare selected ({prepareSelectedIds.length})
        </button>
        <button
          type="button"
          className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-on-accent disabled:opacity-50"
          disabled={busy || operationActive || fillSelectedIds.length === 0 || !browser?.reachable}
          onClick={() => void onStartStage("fill", fillSelectedIds)}
        >
          3. Fill selected ({fillSelectedIds.length})
        </button>
        <span className="ml-auto text-xs text-ink-muted">
          Fill {settings.apply.auto_submit_enabled ? "submits verified forms" : "stops for review"}
        </span>
        {selectedIds.size > fillSelectedIds.length && <span className="text-xs text-warn">{selectedIds.size - fillSelectedIds.length} selected cannot Fill yet{selectedPreparationReasons.length > 0 ? `: ${[...new Set(selectedPreparationReasons)].join(", ").replaceAll("_", " ")}` : ""}</span>}
      </section>

      {operation && (
        <section className="space-y-3 rounded-lg border border-line bg-panel p-4" aria-live="polite">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold capitalize text-ink">
                {operation.action} · {operation.state.replaceAll("_", " ")}
              </p>
              <p className="mt-1 text-sm text-ink-muted">
                {operation.current_label || operation.message || "Waiting to start"}
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                Stage: {operation.stage || "queued"} · Model: {operation.effective_model}
              </p>
              {operation.action === "fill" && operation.total > 0 && <>
                <p className="mt-1 text-xs text-ink-muted">Filling {Math.min(operation.processed + 1, operation.total)} of {operation.total}{operation.current_step > 0 ? ` · Form step ${operation.current_step}` : ""} · Elapsed {Math.max(0, Math.floor((clockNow - Date.parse(operation.application_started_at || operation.started_at || operation.updated_at)) / 1000))}s · Last activity {Math.max(0, Math.floor((clockNow - Date.parse(operation.last_activity_at || operation.events.at(-1)?.at || operation.updated_at)) / 1000))}s ago · Budget {Math.max(0, Math.floor((Date.parse(operation.application_deadline_at || "") - clockNow) / 1000)) || Math.max(0, 240 - Math.floor((clockNow - Date.parse(operation.application_started_at || operation.started_at || operation.updated_at)) / 1000))}s</p>
                <p className="mt-1 text-xs text-ink-muted">{operation.current_action_label || operation.message}{operation.current_field_label ? ` · ${operation.current_field_label}` : ""}</p>
              </>}
            </div>
            <div className="flex gap-2">
              {operation.state === "paused" && (
                <>
                  <button type="button" className="rounded border border-line px-2.5 py-1 text-xs" onClick={() => void controlApplyOperation(operation.operation_id, "resume").then(setOperation)}>Resume</button>
                  <button type="button" className="rounded border border-line px-2.5 py-1 text-xs" onClick={() => void controlApplyOperation(operation.operation_id, "skip").then(setOperation)}>Skip item</button>
                </>
              )}
              {operationActive && (
                <button type="button" className="rounded border border-danger/40 px-2.5 py-1 text-xs text-danger" onClick={() => void controlApplyOperation(operation.operation_id, "cancel").then(setOperation)}>Cancel</button>
              )}
            </div>
          </div>
          {operation.total > 0 && (
            <div className="h-2 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={operation.total} aria-valuenow={operation.processed}>
              <div className="h-full bg-accent transition-all" style={{ width: `${runProgressPercent(operation.processed, operation.total)}%` }} />
            </div>
          )}
          <div className="flex flex-wrap gap-2 text-xs text-ink-muted">
            <span>{operation.processed}/{operation.total} processed</span>
            <span>{operation.action === "fill" ? (operation.ready_for_review ?? operation.completed) : operation.completed} {operation.action === "fill" ? "ready for review" : "completed"}</span>
            {operation.submitted > 0 && <span>{operation.submitted} submitted</span>}
            {(operation.needs_input ?? operation.blocked) > 0 && <span className="text-warn">{operation.needs_input ?? operation.blocked} need input</span>}
            {operation.failed > 0 && <span className="text-danger">{operation.failed} failed</span>}
            {operationActive && operation.heartbeat_at && <span className={clockNow - Date.parse(operation.heartbeat_at) > 15_000 ? "text-warn" : ""}>{clockNow - Date.parse(operation.heartbeat_at) > 15_000 ? "Worker connection appears stale" : "Worker heartbeat"} · {Math.max(0, Math.floor((clockNow - Date.parse(operation.heartbeat_at)) / 1000))}s ago</span>}
          </div>
          {operation.events.length > 0 && (
            <p className="rounded bg-bg px-2 py-1.5 text-xs text-ink-muted">
              Last activity: {operation.events.at(-1)?.message}
            </p>
          )}
          {operation.excluded && Object.keys(operation.excluded).length > 0 && <p className="text-xs text-warn">{Object.keys(operation.excluded).length} selected applications were excluded from Fill: {[...new Set(Object.values(operation.excluded).flat())].join(", ").replaceAll("_", " ")}</p>}
        </section>
      )}

      {!browser?.reachable && (
        <div className="space-y-2 rounded-md border border-line bg-panel p-3 text-xs text-ink-muted">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              Launch a debug-enabled browser for fill (Edge recommended — it won't
              disturb your normal Chrome) — double-click the "ResumeTailor Edge
              (debug)" shortcut if you have one, or run:
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void checkBrowser()}
                disabled={checkingBrowser}
                className="shrink-0 rounded-md border border-line bg-bg px-2.5 py-1 text-xs font-medium text-ink hover:bg-panel disabled:opacity-50"
              >
                {checkingBrowser ? "Checking…" : "↻ Check connection"}
              </button>
              <button
                type="button"
                onClick={() => void onCopyBrowserCommand()}
                className="shrink-0 rounded-md border border-line bg-bg px-2 py-1 text-xs font-medium text-ink"
              >
                {commandCopied ? "Copied!" : "Copy command"}
              </button>
            </div>
          </div>
          <code className="block overflow-x-auto whitespace-pre-wrap break-all">
            {browserCmd}
          </code>
        </div>
      )}

      {error && (
        <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {daily?.running && (
        <section
          className="space-y-2 rounded-lg border border-line bg-panel p-3"
          aria-live="polite"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium text-ink">
              {describePhase(daily)}
              {daily.running && daily.dry_run && (
                <span className="ml-2 rounded bg-warn/15 px-1.5 py-0.5 text-[10px] text-ink">
                  dry run — nothing saved
                </span>
              )}
            </p>
            {daily.running && daily.total > 0 && (
              <span className="text-xs text-ink-muted">
                {runProgressPercent(daily.processed, daily.total)}%
              </span>
            )}
          </div>

          {daily.running && (
            <div
              className="h-1.5 w-full overflow-hidden rounded-full bg-line"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={runProgressPercent(daily.processed, daily.total)}
            >
              <div
                className={`h-full bg-accent transition-all ${
                  daily.total > 0 ? "" : "animate-pulse"
                }`}
                style={{
                  width:
                    daily.total > 0
                      ? `${runProgressPercent(daily.processed, daily.total)}%`
                      : "100%",
                }}
              />
            </div>
          )}

          {daily.summary && (
            <div className="flex flex-wrap gap-1.5">
              {PROGRESS_COUNTERS.map(([key, label]) => {
                const value = Number(daily.summary?.[key] ?? 0);
                if (!value) return null;
                return (
                  <span
                    key={key}
                    className="rounded bg-surface px-1.5 py-0.5 text-[11px] text-ink-muted"
                  >
                    {label} {value}
                  </span>
                );
              })}
              {Array.isArray(daily.summary.errors) && daily.summary.errors.length > 0 && (
                <span
                  className="rounded bg-danger/10 px-1.5 py-0.5 text-[11px] text-danger"
                  title={(daily.summary.errors as string[]).slice(0, 10).join("\n")}
                >
                  errors {(daily.summary.errors as string[]).length}
                </span>
              )}
            </div>
          )}
        </section>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={`rounded-full px-3 py-1 text-xs ${
            filter === "" ? "bg-accent text-on-accent" : "bg-panel text-ink-muted"
          }`}
          onClick={() => changeFilter("")}
        >
          all ({Object.values(counts).reduce((a, b) => a + b, 0)})
        </button>
        {STATUS_CHIPS.map((status) => (
          <button
            key={status}
            type="button"
            className={`rounded-full px-3 py-1 text-xs ${
              filter === status ? "bg-accent text-on-accent" : "bg-panel text-ink-muted"
            }`}
            onClick={() => changeFilter(status)}
          >
            {applicationStatusLabel(status)} ({counts[status] ?? 0})
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
        <span>
          {list && list.total > 0
            ? `Showing ${page * 50 + 1}–${page * 50 + rows.length} of ${list.total} postings`
            : list ? "No postings in this filter" : "Loading postings…"}
          {selectedIds.size > 0 && ` · ${selectedIds.size} selected on this page`}
        </span>
        <div className="flex items-center gap-2">
          <button type="button" className="rounded border border-line px-2 py-1 disabled:opacity-50" disabled={!list || page === 0} onClick={() => changePage(page - 1)}>Previous</button>
          <span>Page {page + 1} of {totalPages}</span>
          <button type="button" className="rounded border border-line px-2 py-1 disabled:opacity-50" disabled={!list || page + 1 >= totalPages} onClick={() => changePage(page + 1)}>Next</button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-panel text-ink-muted">
            <tr>
              <th className="w-10 px-3 py-2 font-medium">
                <input
                  type="checkbox"
                  aria-label="Select all visible applications"
                  checked={rows.length > 0 && rows.every((row) => selectedIds.has(row.source_job_id))}
                  onChange={(e) => setSelectedIds((current) => {
                    const next = new Set(current);
                    for (const row of rows) {
                      if (e.target.checked) next.add(row.source_job_id);
                      else next.delete(row.source_job_id);
                    }
                    return next;
                  })}
                />
              </th>
              <th className="px-3 py-2 font-medium">Company</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Salary</th>
              <th className="px-3 py-2 font-medium">ATS</th>
              <th className="px-3 py-2 font-medium">Coverage</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.source_job_id} className="border-t border-line/60">
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.company} ${row.role}`}
                    checked={selectedIds.has(row.source_job_id)}
                    onChange={() => toggleSelected(row.source_job_id)}
                  />
                </td>
                <td className="px-3 py-2">
                  <div>{row.company}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(row.sources ?? []).map((src) => (
                      <span
                        key={src}
                        className="rounded bg-panel px-1.5 py-0.5 text-[10px] text-ink-muted"
                      >
                        {src}
                      </span>
                    ))}
                    {(row.group_size ?? 1) > 1 && (
                      <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] text-ink">
                        {row.group_size} locations
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1 font-medium text-ink">
                    {row.posting_url ? (
                      <a
                        href={row.posting_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 hover:text-accent hover:underline"
                        title="Open job posting in new tab"
                      >
                        <span>{row.role}</span>
                        <span className="text-[10px] text-ink-muted">↗</span>
                      </a>
                    ) : (
                      <span>{row.role}</span>
                    )}
                  </div>
                  {(row.eligibility_flags?.length ?? 0) > 0 && (
                    <div
                      className="mt-1 flex flex-wrap gap-1"
                      title={row.eligibility_flags.join("; ")}
                    >
                      {row.eligibility_flags.map((flag) => (
                        <span
                          key={flag}
                          className="rounded bg-warn/15 px-1.5 py-0.5 text-[10px] text-ink"
                        >
                          {flag}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-ink-muted">{row.salary || "—"}</td>
                <td className="px-3 py-2">
                  <span className="rounded bg-panel px-1.5 py-0.5 text-xs">{row.ats}</span>
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {row.screen
                    ? `${row.screen.coverage_matched}/${row.screen.coverage_total}`
                    : "—"}
                </td>
                <td className="px-3 py-2">
                  <span>{applicationStatusLabel(row.status)}</span>
                  {row.preparation_reasons && row.preparation_reasons.length > 0 && row.job_id && !isTerminalRow(row) && <p className="mt-1 max-w-56 text-xs text-warn">Needs Prepare: {row.preparation_reasons.join(", ").replaceAll("_", " ")}</p>}
                  {row.fill?.error && <p className="mt-1 max-w-56 text-xs text-danger">{row.fill.error}</p>}
                  {row.status === "awaiting_otp" && <p className="mt-1 max-w-56 text-xs text-warn">Enter the code in the Workday tab, then Continue fill.</p>}
                </td>
                <td className="relative px-3 py-2 whitespace-nowrap">
                  <div className="flex items-center gap-1.5" data-actions-menu>
                    {row.status === "ready" && row.preparation_eligible !== false && (
                      <button
                        type="button"
                        className="rounded bg-accent px-2.5 py-1 text-xs font-medium text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
                        disabled={busy || operationActive}
                        onClick={() => void onFill(row)}
                        title={settings.apply.auto_submit_enabled ? "Fill and submit after verification" : "Fill and stop for review"}
                      >
                        ⚡ Fill
                      </button>
                    )}
                    {row.job_id && row.preparation_eligible === false && !isTerminalRow(row) && <button type="button" className="rounded border border-warn px-2 py-1 text-xs disabled:opacity-50" disabled={busy || operationActive} onClick={() => void onStartStage("prepare", [row.source_job_id], "initial", true)}>Prepare again</button>}
                    {row.fill?.browser_target_id && !["submitted", "filling"].includes(row.status) && <>
                      <button type="button" className="rounded border border-line px-2 py-1 text-xs" onClick={() => void onReviewResults(row)}>Review results</button>
                      <button type="button" className="rounded border border-line px-2 py-1 text-xs" onClick={() => void onReviewTab(row)}>Review tab</button>
                      <button type="button" className="rounded border border-line px-2 py-1 text-xs disabled:opacity-50" disabled={busy || operationActive} title={operationActive ? "Available when the current operation finishes" : "Inspect current answers without changing them"} onClick={() => void onRefreshReview(row)}>Refresh fields</button>
                      {row.status !== "submit_unconfirmed" && <button type="button" className="rounded border border-accent px-2 py-1 text-xs disabled:opacity-50" disabled={busy || operationActive || row.preparation_eligible === false} title={operationActive ? "Available when the current batch finishes" : "Fill remaining fields in this tab without reloading"} onClick={() => void onStartStage("fill", [row.source_job_id], "continue")}>Continue fill</button>}
                    </>}
                    {row.job_id && ["awaiting_review", "awaiting_otp", "fill_failed"].includes(row.status) && <button type="button" className="rounded border border-warn px-2 py-1 text-xs disabled:opacity-50" disabled={busy || operationActive} title="Open a new tab; unsaved answers in the old tab may be lost" onClick={() => void onStartStage("fill", [row.source_job_id], "reopen")}>Reopen and fill</button>}
                    {["awaiting_review", "awaiting_otp", "submit_unconfirmed"].includes(row.status) && <button type="button" className="rounded border border-line px-2 py-1 text-xs" onClick={() => void onMark(row, "submitted")}>Mark submitted</button>}
                    {row.retry_kind && (
                      <button
                        type="button"
                        className={row.retry_kind === "fetch" && row.status === "discovered"
                          ? "rounded border border-accent/40 bg-accent-soft px-2.5 py-1 text-xs font-medium text-ink transition-colors hover:bg-accent hover:text-on-accent disabled:opacity-50"
                          : "rounded border border-warn/30 bg-warn/10 px-2.5 py-1 text-xs font-medium text-warn transition-colors hover:bg-warn/20 disabled:opacity-50"}
                        disabled={busy || operationActive}
                        onClick={() => void onRetry(row)}
                        title={operationActive ? "Available when the current operation finishes" : retryTitle(row.retry_kind)}
                      >
                        {retryLabel(row.retry_kind, row.status)}
                      </button>
                    )}
                    {row.status === "submitted" && (
                      <span className="rounded bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-ink">
                        ✓ Done
                      </span>
                    )}

                    <div className="relative inline-block text-left">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenMenuId((prev) => (prev === row.source_job_id ? null : row.source_job_id));
                        }}
                        className={`rounded border px-2 py-1 text-xs font-medium transition-colors ${
                          openMenuId === row.source_job_id
                            ? "border-accent bg-accent-soft text-ink"
                            : "border-line bg-panel text-ink-muted hover:border-line-hover hover:text-ink"
                        }`}
                        title="More actions"
                      >
                        •••
                      </button>

                      {openMenuId === row.source_job_id && (
                        <div
                          className="absolute right-0 z-30 mt-1 w-44 rounded-md border border-line bg-panel py-1 shadow-lg"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {row.job_id && (
                            <a
                              href={`/api/jobs/${encodeURIComponent(row.job_id)}/preview.pdf`}
                              target="_blank"
                              rel="noreferrer"
                              onClick={() => setOpenMenuId(null)}
                              className="flex items-center gap-2 px-3 py-1.5 text-xs text-ink hover:bg-accent-soft"
                            >
                              <span>📄</span>
                              <span>View PDF</span>
                            </a>
                          )}
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              void onOpenPacket(row);
                            }}
                            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-ink hover:bg-accent-soft"
                          >
                            <span>📋</span>
                            <span>Inspect Packet</span>
                          </button>
                          {row.posting_url && (
                            <a
                              href={row.posting_url}
                              target="_blank"
                              rel="noreferrer"
                              onClick={() => setOpenMenuId(null)}
                              className="flex items-center gap-2 px-3 py-1.5 text-xs text-ink hover:bg-accent-soft"
                            >
                              <span>↗</span>
                              <span>Open Posting</span>
                            </a>
                          )}
                          <div className="my-1 border-t border-line" />
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              void onMark(row, "submitted");
                            }}
                            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-ink hover:bg-accent-soft"
                          >
                            <span>✓</span>
                            <span>Mark Submitted</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              void onMark(row, "skipped");
                            }}
                            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-warn hover:bg-warn-soft"
                          >
                            <span>✕</span>
                            <span>Skip</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-ink-muted">
                      No applications yet. Click Find jobs to discover postings.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {packet && selectedId && (
        <div className="space-y-4 rounded-lg border border-line bg-panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
            <div>
              <h2 className="font-medium text-ink">
                Packet — {packet.company} / {packet.role}
              </h2>
              {packet.job_id && (
                <span className="text-xs text-ink-muted">Job ID: {packet.job_id}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {packet.job_id && (
                <>
                  <a
                    href={`/api/jobs/${encodeURIComponent(packet.job_id)}/preview.pdf`}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-md border border-line bg-bg px-2.5 py-1 text-xs font-medium text-accent hover:bg-panel"
                  >
                    View PDF
                  </a>
                  <a
                    href={`/api/jobs/${encodeURIComponent(packet.job_id)}/download.pdf`}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-md border border-line bg-bg px-2.5 py-1 text-xs font-medium text-ink hover:bg-panel"
                  >
                    Download PDF
                  </a>
                  <a
                    href={`/api/jobs/${encodeURIComponent(packet.job_id)}/download.docx`}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-md border border-line bg-bg px-2.5 py-1 text-xs font-medium text-ink hover:bg-panel"
                  >
                    Download DOCX
                  </a>
                </>
              )}
              <button
                type="button"
                className="text-xs text-ink-muted underline"
                onClick={() => setPacket(null)}
              >
                Close
              </button>
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
              Prepared Answers
            </h3>
            <div className="grid gap-2 sm:grid-cols-2">
              {Object.entries(packet.fields).map(([key, value]) => (
                <div key={key} className="text-xs">
                  <span className="text-ink-muted">{key}: </span>
                  <span className="text-ink">{value}</span>
                </div>
              ))}
            </div>
          </div>

          {packet.skills && packet.skills.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Matched Skills
              </h3>
              <p className="text-xs text-ink-muted">{packet.skills.join(", ")}</p>
            </div>
          )}

          {packet.cover_letter && (
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Cover Letter
              </h3>
              <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded border border-line bg-bg p-2 text-xs text-ink">
                {packet.cover_letter}
              </pre>
            </div>
          )}
        </div>
      )}

      {selectedApplication?.fill && <div id="apply-review-results"><ApplicationReview application={selectedApplication} disabled={busy || operationActive} error={error} onRefresh={() => void onRefreshReview(selectedApplication)} onCorrect={(field, value, optionIds) => void onCorrectField(field, value, optionIds)} /></div>}

      <div className="rounded-lg border border-line">
        <button
          type="button"
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium"
          onClick={() => setProfileOpen((v) => !v)}
        >
          Applicant profile
          <span className="text-ink-muted">{profileOpen ? "Hide" : "Show"}</span>
        </button>
        {profileOpen && profile && (
          <div className="space-y-3 border-t border-line px-4 py-4">
            {(
              [
                ["first_name", "First name"],
                ["middle_name", "Middle name"],
                ["last_name", "Last name"],
                ["preferred_name", "Preferred name"],
                ["email", "Email"],
                ["phone", "Phone"],
                ["phone_device_type", "Phone device type (for example, Mobile)"],
                ["phone_country_code", "Phone country code"],
                ["phone_country_region", "Phone region (optional, for shared calling codes)"],
                ["address_line1", "Address line 1"],
                ["address_line2", "Address line 2"],
                ["city", "City"],
                ["state", "State / province"],
                ["postal_code", "Postal code"],
                ["country", "Country"],
                ["linkedin_url", "LinkedIn URL"],
                ["github_url", "GitHub URL"],
                ["portfolio_url", "Portfolio URL"],
                ["workday_email", "Workday Account Email (blank uses profile email)"],
                ["workday_password", "Workday Account Password"],
                ["earliest_start", "Earliest start (YYYY-MM-DD; full date for application questions)"],
                ["notice_period", "Notice period (separate from start date)"],
                ["authorization_country", "Work authorization country"],
                ["graduation_month", "Graduation (YYYY-MM)"],
                ["degree_level", "Degree level"],
                ["major", "Major"],
                ["school", "School"],
                ["gpa", "GPA"],
                ["salary_expectation", "Saved salary expectation (manual review only; never auto-filled)"],
                ["how_heard", "How heard"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="block text-xs text-ink-muted">
                {label}
                <input
                  type={key === "workday_password" ? "password" : "text"}
                  placeholder={
                    key === "workday_password" && workdayPasswordSet
                      ? "Stored — leave blank to keep it"
                      : undefined
                  }
                  className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-sm text-ink"
                  value={String(profile[key] ?? "")}
                  onChange={(e) => {
                    profileDirtyRef.current = true;
                    setProfileDirty(true);
                    setProfile({ ...profile, [key]: e.target.value });
                  }}
                />
              </label>
            ))}
            <label className="block text-xs text-ink-muted">
              Race category for voluntary self-identification
              <input
                type="text"
                className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-sm text-ink"
                value={profile.eeo.race}
                onChange={(e) => {
                  profileDirtyRef.current = true;
                  setProfileDirty(true);
                  setProfile({ ...profile, eeo: { ...profile.eeo, race: e.target.value } });
                }}
              />
            </label>
            <label className="block text-xs text-ink-muted">
              Preferred race detail (falls back to race category)
              <input
                type="text"
                className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-sm text-ink"
                value={profile.eeo.race_detail ?? ""}
                onChange={(e) => {
                  profileDirtyRef.current = true;
                  setProfileDirty(true);
                  setProfile({ ...profile, eeo: { ...profile.eeo, race_detail: e.target.value } });
                }}
              />
            </label>
            <label className="block text-xs text-ink-muted">
              Hispanic/Latino (separate voluntary question)
              <select
                className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-sm text-ink"
                value={profile.eeo.hispanic_latino == null ? "" : profile.eeo.hispanic_latino ? "yes" : "no"}
                onChange={(e) => {
                  profileDirtyRef.current = true;
                  setProfileDirty(true);
                  setProfile({ ...profile, eeo: { ...profile.eeo, hispanic_latino: e.target.value === "" ? null : e.target.value === "yes" } });
                }}
              >
                <option value="">Not answered</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
            <label className="block text-xs text-ink-muted">
              Work authorization
              <select
                className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-sm text-ink"
                value={profile.work_authorization}
                onChange={(e) => {
                  profileDirtyRef.current = true;
                  setProfileDirty(true);
                  setProfile({ ...profile, work_authorization: e.target.value });
                }}
              >
                <option value="">Not answered</option>
                <option value="citizen">Citizen</option>
                <option value="permanent_resident">Permanent resident</option>
                <option value="visa_holder">Visa holder</option>
                <option value="other">Other</option>
              </select>
            </label>
            {([
              ["authorized_to_work", "Authorized to work in the specified country"],
              ["requires_sponsorship_now", "Requires sponsorship now"],
              ["requires_sponsorship_future", "Requires sponsorship in future"],
              ["f1_opt_eligible", "F-1 OPT eligible"],
              ["willing_to_relocate", "Willing to relocate"],
              ["over_18", "Over 18"],
              ["relatives_at_company", "Relatives at company"],
            ] as const).map(([key, label]) => (
              <label key={key} className="block text-xs text-ink-muted">
                {label}
                <select
                  className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-sm text-ink"
                  value={profile[key] == null ? "" : profile[key] ? "yes" : "no"}
                  onChange={(e) => {
                    profileDirtyRef.current = true;
                    setProfileDirty(true);
                    setProfile({
                      ...profile,
                      [key]: e.target.value === "" ? null : e.target.value === "yes",
                    });
                  }}
                >
                  <option value="">Not answered</option>
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              </label>
            ))}
            <button
              type="button"
              className="rounded-md bg-accent px-3 py-1.5 text-sm text-on-accent disabled:opacity-50"
              disabled={busy}
              onClick={() => void onSaveProfile()}
            >
              {profileDirty ? "Save profile" : "Saved"}
            </button>
          </div>
        )}
      </div>


    </div>
  );
}

/** Count helper exported for vitest. */
export function sumStatusCounts(counts: Record<string, number>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0);
}
