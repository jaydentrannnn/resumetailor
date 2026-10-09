import { useCallback, useEffect, useRef, useState } from "react";
import {
  controlApplyOperation,
  getApplyOperation,
  getBrowserStatus,
  getDailyStatus,
  launchBrowser,
  listApplyOperations,
  runDailyNow,
  type ApplicationsList,
  type ApplyOperation,
  type BrowserId,
  type BrowserStatus,
  type DailyStatus,
} from "../../api";
import { startAdaptivePoll } from "../../lib/adaptivePoll";
import {
  type ApplySnapshot,
  applyNotifications,
  notifyPreference,
  setNotifyPreference,
} from "../../lib/applyNotify";
import { pollSignature, shouldRefreshTables } from "../../lib/applyPoll";
import { browserView } from "../../lib/browserState";
import { useToast } from "../../lib/toast";
import type { OperationControl } from "./OperationBanner";

export const ACTIVE_STATES = ["queued", "running", "paused"];
const notificationsSupported = () => typeof window !== "undefined" && "Notification" in window;

/**
 * The page's live state: the current (or last) Apply task, the nightly run, browser
 * reachability and desktop notifications. One adaptive poll reads the task and the
 * nightly run; it refreshes the tables only when either changes.
 */
export function useApplyOperation({
  workspaceId,
  refresh,
  inFlight,
  review,
  tabsReachable,
  selectedBrowser,
  showError,
}: {
  workspaceId: string;
  refresh: () => void;
  /** Whether any visible row is mid-tailor or mid-fill (keeps the poll fast). */
  inFlight: boolean;
  /** The Needs you table's data, for notifications. */
  review: ApplicationsList | null;
  tabsReachable: boolean | null;
  /** The browser chosen in Apply settings (null = automatic). */
  selectedBrowser: BrowserId | null;
  showError: (title: string, reason: unknown) => void;
}) {
  const toast = useToast();
  const [operation, setOperation] = useState<ApplyOperation | null>(null);
  const [daily, setDaily] = useState<DailyStatus | null>(null);
  const dailyRunning = daily?.running ?? false;
  const [browserStatus, setBrowserStatus] = useState<BrowserStatus | null>(null);
  const [launching, setLaunching] = useState(false);
  const browser = browserView(browserStatus, selectedBrowser);
  // Ready, or the app will start it when Fill needs it.
  const browserUsable = browser.state !== "unavailable";
  const [notify, setNotify] = useState(notifyPreference);
  const active = dailyRunning || (!!operation && ACTIVE_STATES.includes(operation.state));

  // The poll reads these through refs so it never restarts (and forgets what it saw)
  // when the tab changes or the rows change.
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const inFlightRef = useRef(false);
  inFlightRef.current = inFlight;
  const wakePollRef = useRef<() => void>(() => {});
  const wake = useCallback(() => wakePollRef.current(), []);

  const checkBrowser = useCallback(() => {
    getBrowserStatus()
      .then(setBrowserStatus)
      .catch(() => {});
  }, []);
  // The open-tabs poll notices the browser opening or closing; a task starting or ending
  // may have launched it.
  const operationState = operation?.state;
  useEffect(checkBrowser, [checkBrowser, workspaceId, tabsReachable, operationState]);

  async function startBrowser() {
    setLaunching(true);
    try {
      setBrowserStatus(await launchBrowser());
    } catch (reason) {
      showError("Could not start the browser", reason);
    } finally {
      setLaunching(false);
    }
  }

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
    if (!review || !daily) return;
    const snapshot: ApplySnapshot = {
      needsYou: review.total,
      otp: review.applications
        .filter((row) => row.status === "awaiting_otp")
        .map((row) => `${row.source_job_id}:${row.company}`),
      // A Find jobs runs the same pass with `fetch_only`; it isn't the nightly run.
      dailyRunning: daily.running && !daily.fetch_only,
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
  }, [review, daily, operation, notify]);

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

  function control(action: OperationControl) {
    if (!operation) return;
    void controlApplyOperation(operation.operation_id, action)
      .then(setOperation)
      .catch((reason) => showError("Could not change the task", reason))
      .finally(wake);
  }

  async function runNow() {
    try {
      setDaily(await runDailyNow());
      toast.info("Nightly run started", "Finding, checking and tailoring new postings.");
    } catch (reason) {
      showError("Could not start the nightly run", reason);
    } finally {
      wake();
    }
  }

  return {
    operation,
    setOperation,
    daily,
    dailyRunning,
    active,
    browser,
    browserStatus,
    browserUsable,
    checkBrowser,
    launchBrowser: { run: () => void startBrowser(), busy: launching },
    wake,
    control,
    runNow,
    notify: {
      enabled: notify,
      supported: notificationsSupported(),
      onChange: (on: boolean) => void changeNotify(on),
    },
  };
}
