import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  archiveApplications,
  acknowledgeApplicationResume,
  getApplication,
  controlApplyOperation,
  focusApplicationReviewTab,
  getApplyOperation,
  getBrowserStatus,
  getDailyStatus,
  listApplications,
  listApplyOperations,
  retryApplication,
  runDailyNow,
  setApplicationStatus,
  startApplyOperation,
  undoSubmitted,
  type ApplicationRow,
  type ApplyOperation,
  type DailyStatus,
} from "../../api";
import { ProfileGapsNotice } from "../../components/ProfileGapsNotice";
import { Tabs } from "../../components/Tabs";
import { Button, EmptyState, Skeleton } from "../../components/ui";
import { startAdaptivePoll } from "../../lib/adaptivePoll";
import {
  consumeApplicationListScroll,
  recallApplyParams,
  rememberApplicationListScroll,
  rememberApplyParams,
} from "../../lib/applicationNavigation";
import {
  canContinueFill,
  canReopenFill,
  isTabClosed,
  canFillAfterReview,
} from "../../lib/applicationRows";
import {
  type ApplySnapshot,
  applyNotifications,
  notifyPreference,
  setNotifyPreference,
} from "../../lib/applyNotify";
import {
  fillBlockers,
  nightlyRunLabel,
  resolveApplyTab,
  SOURCES_PATH,
  TERMINAL_STATUSES,
  canRetailor,
  type ApplyTab,
} from "../../lib/applyPage";
import { IN_FLIGHT_STATUSES, pollSignature, shouldRefreshTables } from "../../lib/applyPoll";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useOpenTabs } from "../../lib/useOpenTabs";
import { useProfileGaps } from "../../state/applicantProfileState";
import { useConfirm } from "../../state/confirmState";
import { useRunState } from "../../state/runState";
import { useWorkspaceState } from "../../state/workspaceState";
import { ApplicationsTable, type TableActions } from "./ApplicationsTable";
import { ApplySettingsDrawer } from "./ApplySettingsDrawer";
import { ConnectionStatus } from "./BrowserConnection";
import { OperationBanner, type OperationControl } from "./OperationBanner";
import { ProgressToolbar } from "./ProgressToolbar";
import { AttentionList } from "./AttentionList";
import { useSourcesStatus } from "./sourceHooks";
import { NeedsDescriptionGroup } from "../CapturedStubs";
import { useApplicationTable } from "./useApplicationTable";

const ACTIVE_STATES = ["queued", "running", "paused"];
const notificationsSupported = () => typeof window !== "undefined" && "Notification" in window;

/**
 * Apply: postings found for the student, split into Needs you / In progress / Done,
 * with the current Apply task pinned on top and every setting in a side drawer.
 */
export function ApplyPage() {
  const { settings, setSettings, config } = useRunState();
  const { activeId } = useWorkspaceState();
  const { confirm } = useConfirm();
  const toast = useToast();
  const profileGaps = useProfileGaps();
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  // Sources used to be a tab here; old links and bookmarks land on its own page.
  useEffect(() => {
    if (params.get("tab") === "sources") navigate(SOURCES_PATH, { replace: true });
  }, [params, navigate]);
  const workspaceId = activeId ?? "";
  // Leaving Apply and coming back (the nav link carries no params) restores the same
  // tab, page, sort and filters.
  const paramString = params.toString();
  useEffect(() => {
    if (!paramString) {
      const saved = recallApplyParams(workspaceId);
      if (saved) {
        setParams(new URLSearchParams(saved), { replace: true });
        return;
      }
    }
    if (params.get("tab") !== "sources") rememberApplyParams(workspaceId, paramString);
  }, [paramString, params, workspaceId, setParams]);
  // One search covers every tab; `search` is the debounced value the tables query with.
  const q = params.get("q") ?? "";
  const [search, setSearch] = useState(q);
  useEffect(() => {
    const id = window.setTimeout(() => setSearch(q), 250);
    return () => window.clearTimeout(id);
  }, [q]);
  const review = useApplicationTable("review", workspaceId, params, setParams, true, search);
  const queue = useApplicationTable("queue", workspaceId, params, setParams, true, search);
  const tab: ApplyTab = resolveApplyTab(params.get("tab"), review.data ? review.data.total : null);
  const tabDecided = params.has("tab") || review.data != null;
  const archive = useApplicationTable(
    "archive",
    workspaceId,
    params,
    setParams,
    tab === "done" || search !== "",
    search,
  );
  const [archiveTotal, setArchiveTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [operation, setOperation] = useState<ApplyOperation | null>(null);
  const [daily, setDaily] = useState<DailyStatus | null>(null);
  const dailyRunning = daily?.running ?? false;
  const [browserConnected, setBrowserConnected] = useState(false);
  const { openTabs, reachable: tabsReachable, recheck: recheckTabs } = useOpenTabs();
  useEffect(() => {
    if (tabsReachable != null) setBrowserConnected(tabsReachable);
  }, [tabsReachable]);
  const [busy, setBusy] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [limit, setLimit] = useState("");
  // null follows the saved setting; a number widens or narrows the next Find only.
  const [ageDays, setAgeDays] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(params.get("settings") === "1");
  const [notify, setNotify] = useState(notifyPreference);
  const active = dailyRunning || (!!operation && ACTIVE_STATES.includes(operation.state));
  // Re-read each source's health whenever a run starts or finishes.
  const sourcesStatus = useSourcesStatus(active);

  const showError = useCallback(
    (title: string, reason: unknown) => toast.error(title, describe(reason).detail),
    [toast],
  );

  function setQuery(value: string) {
    setParams(
      (previous) => {
        const out = new URLSearchParams(previous);
        if (value) out.set("q", value);
        else out.delete("q");
        for (const scope of ["review", "queue", "archive"]) out.delete(`${scope}_page`);
        return out;
      },
      { replace: true },
    );
  }

  function setTab(next: string) {
    setParams(
      (previous) => {
        const out = new URLSearchParams(previous);
        out.set("tab", next);
        return out;
      },
      { replace: true },
    );
  }

  const scrollRestored = useRef(false);
  useEffect(() => {
    if (scrollRestored.current || !queue.data) return;
    const position = consumeApplicationListScroll(workspaceId);
    if (position == null) return;
    scrollRestored.current = true;
    window.requestAnimationFrame(() => window.scrollTo(0, position));
  }, [workspaceId, queue.data]);

  const refreshQueue = queue.refresh;
  const refreshArchive = archive.refresh;
  const refreshReview = review.refresh;
  const refresh = useCallback(() => {
    refreshQueue();
    refreshReview();
    if (tab === "done" || search) refreshArchive();
    recheckTabs();
    setRevision((n) => n + 1);
  }, [refreshQueue, refreshReview, refreshArchive, tab, search, recheckTabs]);
  // The poll reads these through refs so it never restarts (and forgets what it saw)
  // when the tab changes or the rows change.
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const inFlightRef = useRef(false);
  const wakePollRef = useRef<() => void>(() => {});
  inFlightRef.current = [queue.data, review.data].some((data) =>
    data?.applications.some((row) => IN_FLIGHT_STATUSES.has(row.status)),
  );

  useEffect(() => {
    let live = true;
    listApplications({ archive: "archived", limit: 1 })
      .then((result) => live && setArchiveTotal(result.total))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [workspaceId, revision]);

  const checkBrowser = useCallback(() => {
    getBrowserStatus()
      .then((result) => setBrowserConnected(result.reachable))
      .catch(() => {});
  }, []);
  useEffect(checkBrowser, [checkBrowser, workspaceId]);

  useEffect(() => {
    let live = true;
    let seen: string | null = null;
    // Resolves to whether anything is in flight, which sets the next poll's delay.
    async function poll(): Promise<boolean> {
      const [operations, day] = await Promise.all([listApplyOperations(), getDailyStatus()]);
      if (!live) return false;
      setDaily(day);
      const current = operations.find((op) => ACTIVE_STATES.includes(op.state)) ?? operations[0];
      const latest = current ? await getApplyOperation(current.operation_id) : null;
      if (!live) return false;
      setOperation(latest);
      const snapshot = {
        operationId: latest?.operation_id ?? null,
        state: latest?.state ?? null,
        dailyRunning: day.running,
      };
      if (shouldRefreshTables(seen, snapshot, inFlightRef.current)) refreshRef.current();
      seen = pollSignature(snapshot);
      const operationActive = ACTIVE_STATES.includes(latest?.state ?? "");
      return operationActive || day.running || inFlightRef.current;
    }
    const { stop, wake } = startAdaptivePoll(poll);
    wakePollRef.current = wake;
    return () => {
      live = false;
      wakePollRef.current = () => {};
      stop();
    };
  }, []);

  // Desktop notifications for what changed since the last look (A6).
  const lastSnapshot = useRef<ApplySnapshot | null>(null);
  useEffect(() => {
    if (!review.data || !daily) return;
    const snapshot: ApplySnapshot = {
      needsYou: review.data.total,
      otp: review.data.applications
        .filter((row) => row.status === "awaiting_otp")
        .map((row) => `${row.source_job_id}:${row.company}`),
      dailyRunning: daily.running,
      dailySummary: daily.summary,
      operationId: operation?.operation_id ?? null,
      operationState: operation?.state ?? null,
      operationAction: operation?.action ?? null,
      readyForReview: operation?.ready_for_review ?? operation?.completed ?? 0,
    };
    const messages = applyNotifications(lastSnapshot.current, snapshot);
    lastSnapshot.current = snapshot;
    if (!notify || !notificationsSupported() || Notification.permission !== "granted") return;
    for (const body of messages) new Notification("ResumeTailor", { body, tag: body });
  }, [review.data, daily, operation, notify]);

  async function changeNotify(on: boolean) {
    if (on && notificationsSupported() && Notification.permission === "default")
      await Notification.requestPermission();
    const granted = notificationsSupported() && Notification.permission === "granted";
    if (on && !granted)
      toast.error(
        "Notifications are blocked",
        "Allow notifications for this site in your browser settings, then try again.",
      );
    setNotify(on && granted);
    setNotifyPreference(on && granted);
  }

  async function start(
    action: "find" | "prepare" | "fill",
    ids: string[] = [],
    mode: "initial" | "continue" | "reopen" = "initial",
    force = false,
  ) {
    setBusy(true);
    try {
      if (action === "fill") {
        const current = await Promise.all(ids.map((id) => getApplication(id)));
        const flagged = current.filter((item) => item.application.resume_review?.required);
        if (flagged.some((item) => !item.application.resume_review?.quality.verified)) {
          toast.error(
            "Prepare these resumes again",
            "Resume quality could not be verified. Open the application details to review.",
          );
          return;
        }
        if (flagged.length) {
          const accepted = await confirm({
            title: "Review resume warnings before Fill",
            message: flagged
              .map(
                ({ application: app }) =>
                  `${app.company} — ${app.role}:\n${app.resume_review!.warnings.join("\n")}`,
              )
              .join("\n\n"),
            confirmLabel: "Use these resumes anyway",
          });
          if (!accepted) return;
          await Promise.all(
            flagged.map(({ application: app }) =>
              acknowledgeApplicationResume(app.source_job_id, app.resume_review!.revision),
            ),
          );
        }
      }
      setOperation(
        await startApplyOperation({
          action,
          application_ids: ids,
          fill_mode: mode,
          force_prepare: force,
          limit: Number(limit) > 0 ? Number(limit) : null,
          max_age_days: action === "find" ? ageDays : null,
          dry_run: action === "find" && dryRun,
          auto_submit: settings.apply.auto_submit_enabled,
          blocker_mode: "continue",
          model_provider: settings.apply.model_provider,
          model_name: settings.apply.model_name,
        }),
      );
    } catch (reason) {
      showError("Could not start", reason);
    } finally {
      setBusy(false);
      wakePollRef.current();
    }
  }

  /** Reopen in fresh tabs; ask first only when a tab that may hold unsaved answers is still open. */
  function reopen(rows: ApplicationRow[]) {
    const ids = rows.map((row) => row.source_job_id);
    if (!ids.length) return;
    if (!rows.some((row) => row.fill?.browser_target_id && !isTabClosed(row, openTabs))) {
      void start("fill", ids, "reopen");
      return;
    }
    const many = ids.length > 1;
    void confirm({
      title: many ? `Reopen ${ids.length} application tabs?` : "Reopen application tab?",
      message: many
        ? "Unsaved answers in tabs that are still open may be lost."
        : "Unsaved answers in the old browser tab may be lost.",
      confirmLabel: "Reopen and fill",
    }).then((ok) => {
      if (ok) void start("fill", ids, "reopen");
    });
  }

  /**
   * Tailor files again, even when the current files are fine. A row whose filled tab is
   * still open asks first: the new files replace the ones that tab was filled with.
   */
  function retailor(rows: ApplicationRow[]) {
    const ids = rows.filter(canRetailor).map((row) => row.source_job_id);
    if (!ids.length) return;
    const filled = rows.filter(
      (row) => canRetailor(row) && row.fill?.browser_target_id && !isTabClosed(row, openTabs),
    );
    if (!filled.length) {
      void start("prepare", ids, "initial", true);
      return;
    }
    const many = filled.length > 1;
    void confirm({
      title: many ? `Tailor files again for ${ids.length} applications?` : "Tailor files again?",
      message: many
        ? `${filled.length} of them have an application tab already filled with the current files. Fill them again afterwards to upload the new resume.`
        : "The open application tab was filled with the current files. Fill it again afterwards to upload the new resume.",
      confirmLabel: "Tailor files again",
    }).then((ok) => {
      if (ok) void start("prepare", ids, "initial", true);
    });
  }

  async function move(ids: string[], archived: boolean, undoable = true) {
    if (!ids.length) return;
    setBusy(true);
    try {
      const result = await archiveApplications(ids, archived);
      if (result.updated.length) {
        for (const table of [queue, review, archive]) table.deselect(result.updated);
        const n = result.updated.length;
        const title = `${n} application${n === 1 ? "" : "s"} ${archived ? "moved to Done" : "restored"}`;
        if (undoable)
          toast.success(title, undefined, {
            label: "Undo",
            onClick: () => void move(result.updated, !archived, false),
          });
        else toast.success(title);
        refresh();
      }
      const failures = Object.entries(result.errors);
      if (failures.length)
        toast.error(
          "Some applications were not moved",
          failures.map(([id, message]) => `${id}: ${message}`).join("; "),
        );
    } catch (reason) {
      showError("Could not move applications", reason);
    } finally {
      setBusy(false);
    }
  }

  /** Skip the rows in one go; like Archive, Undo puts them back instead of asking first. */
  async function skip(rows: ApplicationRow[]) {
    if (!rows.length) return;
    setBusy(true);
    try {
      const results = await Promise.allSettled(
        rows.map((row) => setApplicationStatus(row.source_job_id, "skipped")),
      );
      const done: string[] = [];
      const failures: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled") done.push(rows[index].source_job_id);
        else failures.push(`${rows[index].company}: ${describe(result.reason).detail}`);
      });
      if (done.length) {
        for (const table of [queue, review, archive]) table.deselect(done);
        const n = done.length;
        toast.success(`${n} application${n === 1 ? "" : "s"} skipped`, "Moved to Done.", {
          label: "Undo",
          onClick: () => void unskip(done),
        });
      }
      if (failures.length) toast.error("Some applications were not skipped", failures.join("; "));
      refresh();
    } finally {
      setBusy(false);
    }
  }

  /** Skipping moves a row to Done; restoring it from Done is what undoes the skipped mark. */
  async function unskip(ids: string[]) {
    try {
      const result = await archiveApplications(ids, false);
      const failures = Object.entries(result.errors);
      if (failures.length)
        toast.error(
          "Some applications could not be restored",
          failures.map(([id, message]) => `${id}: ${message}`).join("; "),
        );
    } catch (reason) {
      showError("Could not undo the skip", reason);
    }
    refresh();
  }

  async function retry(row: ApplicationRow) {
    setBusy(true);
    try {
      await retryApplication(row.source_job_id);
      refresh();
    } catch (reason) {
      showError("Could not retry", reason);
    } finally {
      setBusy(false);
    }
  }

  async function mark(row: ApplicationRow, status: "submitted" | "skipped") {
    try {
      const updated = await setApplicationStatus(row.source_job_id, status);
      // Submitting and skipping move the row to Done server-side; say so.
      if (updated.archived_at)
        toast.success(
          `${row.company} marked ${status === "submitted" ? "submitted" : "skipped"}`,
          "Moved to Done.",
        );
      refresh();
    } catch (reason) {
      showError("Could not update the status", reason);
    }
  }

  async function undo(row: ApplicationRow) {
    setBusy(true);
    try {
      await undoSubmitted(row.source_job_id);
      refresh();
    } catch (reason) {
      showError("Could not move application back", reason);
    } finally {
      setBusy(false);
    }
  }

  function control(action: OperationControl) {
    if (!operation) return;
    void controlApplyOperation(operation.operation_id, action)
      .then(setOperation)
      .catch((reason) => showError("Could not change the task", reason))
      .finally(() => wakePollRef.current());
  }

  async function runNow() {
    try {
      setDaily(await runDailyNow());
      toast.info("Nightly run started", "Finding, checking and tailoring new postings.");
    } catch (reason) {
      showError("Could not start the nightly run", reason);
    } finally {
      wakePollRef.current();
    }
  }

  const actions: TableActions = {
    busy,
    active,
    browserConnected,
    openTabs,
    start: (action, ids, mode, force) => void start(action, ids, mode, force),
    reopen,
    retailor,
    move: (ids, archived) => void move(ids, archived),
    undo: (row) => void undo(row),
    retry: (row) => void retry(row),
    mark: (row, status) => void mark(row, status),
    skip: (rows) => void skip(rows),
    focusTab: (row) =>
      void focusApplicationReviewTab(row.source_job_id).catch((reason) =>
        showError("Could not open the tab", reason),
      ),
    detail: (row, detailTab = "overview") => ({
      pathname: `/applications/${encodeURIComponent(row.source_job_id)}`,
      search: `?tab=${detailTab}`,
      state: { from: `${location.pathname}${location.search}`, archive: !!row.archived_at },
    }),
    rememberScroll: () => rememberApplicationListScroll(workspaceId),
  };

  const queueSelected = queue.selectedRows;
  const prepareIds = queueSelected
    .filter((row) => !TERMINAL_STATUSES.has(row.status))
    .map((row) => row.source_job_id);
  const retailorRows = queueSelected.filter(canRetailor);
  const fillIds = queueSelected
    .filter((row) => row.status === "ready" && canFillAfterReview(row))
    .map((row) => row.source_job_id);
  const blockers = fillBlockers(queueSelected);
  const reviewSelected = review.selectedRows;
  const continueIds = reviewSelected
    .filter((row) => canContinueFill(row, openTabs))
    .map((row) => row.source_job_id);
  const reopenRows = reviewSelected.filter(canReopenFill);
  const readyCount = (queue.data?.counts.ready ?? 0) + (review.data?.total ?? 0);
  const anySource = settings.apply.sources.some((source) => source.enabled);
  const notConnected = "Connect the browser in Apply settings first";
  const idleNote = active ? "Available when the current Apply task finishes" : undefined;

  const progressToolbar = (
    <ProgressToolbar
      apply={settings.apply}
      sourcesStatus={sourcesStatus}
      options={{ limit, dryRun, ageDays }}
      onOptions={(next) => {
        setLimit(next.limit);
        setDryRun(next.dryRun);
        setAgeDays(next.ageDays);
      }}
      busy={busy}
      active={active}
      anySource={anySource}
      browserConnected={browserConnected}
      prepareCount={prepareIds.length}
      retailorCount={retailorRows.length}
      fillCount={fillIds.length}
      blockers={blockers}
      onFind={() => void start("find")}
      onPrepare={() => void start("prepare", prepareIds)}
      onRetailor={() => retailor(retailorRows)}
      onFill={() => void start("fill", fillIds)}
      onManageSources={() => navigate(SOURCES_PATH)}
    />
  );

  const reviewToolbar = reviewSelected.length > 0 && (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel p-3 text-sm">
      <Button
        variant="secondary"
        disabled={busy || active || !continueIds.length || !browserConnected}
        title={
          idleNote ?? (browserConnected ? "Resume the fills in their open tabs" : notConnected)
        }
        onClick={() => void start("fill", continueIds, "continue")}
      >
        Continue fill ({continueIds.length})
      </Button>
      <Button
        variant="secondary"
        disabled={busy || active || !reopenRows.length || !browserConnected}
        title={
          idleNote ??
          (browserConnected ? "Open the postings again and fill from the start" : notConnected)
        }
        onClick={() => reopen(reopenRows)}
      >
        Reopen and fill ({reopenRows.length})
      </Button>
      {reviewSelected.length > continueIds.length && (
        <span className="ml-auto text-xs text-ink-muted">
          {reviewSelected.length - continueIds.length} selected can't continue (tab closed or not
          started)
        </span>
      )}
    </div>
  );

  // A new search that finds nothing on this tab jumps to the first tab that has matches,
  // once per search, so it never fights a tab the user clicks afterwards.
  const switchedFor = useRef("");
  const doneCount = search ? (archive.data?.total ?? 0) : archiveTotal;
  useEffect(() => {
    if (!search) {
      switchedFor.current = "";
      return;
    }
    const tables = { needs: review, progress: queue, done: archive };
    const trimmed = search.trim();
    if (switchedFor.current === search || Object.values(tables).some((t) => t.dataQ !== trimmed))
      return;
    switchedFor.current = search;
    const total = (id: ApplyTab) => tables[id].data?.total ?? 0;
    if (total(tab) > 0) return;
    const hit = (["needs", "progress", "done"] as const).find((id) => total(id) > 0);
    if (hit) setTab(hit);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setTab only writes the URL
  }, [
    search,
    tab,
    review.dataQ,
    queue.dataQ,
    archive.dataQ,
    review.data,
    queue.data,
    archive.data,
  ]);

  const lastChecked = daily?.scheduler?.last_started_at;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-semibold">Applications</h1>
          <p className="text-sm text-ink-muted">
            Find postings, tailor your files for each one, and track every application.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <button
            type="button"
            className={`rounded-full border px-3 py-1 text-xs font-medium ${settings.apply.enabled ? "border-accent/40 bg-accent-soft text-accent" : "border-line bg-panel text-ink-muted"}`}
            title="Change the nightly run in Apply settings"
            onClick={() => setDrawerOpen(true)}
          >
            {nightlyRunLabel(settings.apply)}
          </button>
          <ConnectionStatus connected={browserConnected} />
          <Button variant="secondary" onClick={() => setDrawerOpen(true)}>
            Apply settings
          </Button>
        </div>
      </header>

      <ProfileGapsNotice gaps={profileGaps} />

      {operation && <OperationBanner operation={operation} onControl={control} />}
      {daily?.summary && (daily.running || daily.finished_at) && (
        <section
          className="rounded-lg border border-line bg-panel p-4 shadow-sm"
          aria-live="polite"
        >
          <h2 className="text-lg font-semibold">
            Nightly run {daily.running ? "in progress" : "finished"}
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            {daily.processed} of {daily.total} processed{daily.current ? ` · ${daily.current}` : ""}
          </p>
          <AttentionList items={daily.summary.attention} />
        </section>
      )}

      {!browserConnected && readyCount > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warn/40 bg-warn-soft/30 p-3 text-sm">
          <span>
            <strong>Connect your browser to fill applications.</strong>{" "}
            <span className="text-ink-muted">
              {readyCount} application{readyCount === 1 ? " is" : "s are"} ready or waiting on you.
            </span>
          </span>
          <Button className="ml-auto" variant="secondary" onClick={() => setDrawerOpen(true)}>
            Set up
          </Button>
        </div>
      )}

      {!tabDecided ? (
        <Skeleton className="h-48" />
      ) : (
        <>
          <div className="relative">
            <input
              className="w-full rounded-md border border-line bg-panel py-2 pl-3 pr-9 text-sm"
              aria-label="Search applications"
              data-shortcut="search"
              placeholder="Search every tab by company, role, or location"
              value={q}
              onChange={(e) => setQuery(e.target.value)}
            />
            {q && (
              <button
                type="button"
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 px-1.5 text-ink-muted hover:text-ink"
                onClick={() => setQuery("")}
              >
                ×
              </button>
            )}
          </div>
          <Tabs
            label="Applications"
            items={[
              { id: "needs", label: `Needs you (${review.data?.total ?? 0})` },
              { id: "progress", label: `In progress (${queue.data?.total ?? 0})` },
              { id: "done", label: `Done (${doneCount})` },
            ]}
            value={tab}
            onChange={setTab}
          />
          <div role="tabpanel">
            {tab === "needs" && <NeedsDescriptionGroup />}
            {tab === "needs" && (
              <ApplicationsTable
                scope="review"
                state={review}
                actions={actions}
                onClearSearch={() => setQuery("")}
                toolbar={reviewToolbar}
                empty={
                  <EmptyState title="Nothing needs you right now">
                    Applications that need a sign-in, an emailed code or an answer only you can give
                    will show up here.
                  </EmptyState>
                }
              />
            )}
            {tab === "progress" && (
              <ApplicationsTable
                scope="queue"
                state={queue}
                actions={actions}
                onClearSearch={() => setQuery("")}
                toolbar={progressToolbar}
                empty={
                  !anySource ? (
                    <EmptyState
                      title="Choose what to search for"
                      action={
                        <Button variant="primary" onClick={() => navigate(SOURCES_PATH)}>
                          Pick job sources
                        </Button>
                      }
                    >
                      Every job board is turned off, so there is nothing to find.
                    </EmptyState>
                  ) : (
                    <EmptyState
                      title="No new postings"
                      action={
                        <Button
                          variant="primary"
                          disabled={busy || active}
                          onClick={() => void start("find")}
                        >
                          Find jobs now
                        </Button>
                      }
                    >
                      {lastChecked
                        ? `Last checked ${new Date(lastChecked).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}.`
                        : "Nothing has been searched yet."}
                      {archiveTotal > 0 && (
                        <>
                          {" "}
                          <button
                            type="button"
                            className="text-accent underline"
                            onClick={() => setTab("done")}
                          >
                            See finished applications
                          </button>
                        </>
                      )}
                    </EmptyState>
                  )
                }
              />
            )}
            {tab === "done" && (
              <ApplicationsTable
                scope="archive"
                state={archive}
                actions={actions}
                onClearSearch={() => setQuery("")}
                empty={
                  <EmptyState title="Nothing finished yet">
                    Submitted, skipped and archived applications appear here.
                  </EmptyState>
                }
              />
            )}
          </div>
        </>
      )}

      {drawerOpen && (
        <ApplySettingsDrawer
          settings={settings}
          setSettings={setSettings}
          config={config}
          onClose={() => {
            setDrawerOpen(false);
            if (params.has("settings"))
              setParams(
                (previous) => {
                  const out = new URLSearchParams(previous);
                  out.delete("settings");
                  return out;
                },
                { replace: true },
              );
          }}
          scheduler={daily?.scheduler ?? null}
          dailyRunning={dailyRunning}
          onRunNow={() => void runNow()}
          browserConnected={browserConnected}
          onCheckBrowser={checkBrowser}
          notify={{
            enabled: notify,
            supported: notificationsSupported(),
            onChange: (on) => void changeNotify(on),
          }}
        />
      )}
    </div>
  );
}
