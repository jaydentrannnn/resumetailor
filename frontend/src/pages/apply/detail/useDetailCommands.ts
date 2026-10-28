import { useState } from "react";
import {
  archiveApplications,
  retryApplication,
  setApplicationStatus,
  startApplyOperation,
  type ApplicationRow,
} from "../../../api";
import {
  canMark,
  nextAction,
  operationRequest,
  resumeWarningsAccepted,
  retryAction,
  type NextAction,
} from "../../../lib/applicationActions";
import { canContinueWithNewFiles, isTabClosed, type OpenTabs } from "../../../lib/applicationRows";
import { describe } from "../../../lib/errors";
import { announceTabsChanged } from "../../../lib/tabsChanged";
import { useToast } from "../../../lib/toast";
import { useConfirm } from "../../../state/confirmState";
import { useRunState } from "../../../state/runState";

/** Statuses a running task is working on: marking the row stops that task first. */
const WORKING = new Set(["filling", "tailoring"]);

export interface DetailCommands {
  next: NextAction;
  /** The primary button's label; null when the next step is only to look. */
  label: string | null;
  working: boolean;
  runNext: () => void;
  /** Mark submitted and Skip are offered on every unfinished application. */
  canMark: boolean;
  mark: (status: "submitted" | "skipped") => void;
}

/**
 * The application page's own actions (audit #19): its next step, Mark submitted and Skip
 * with Undo, by the same rules as its row on Apply (`lib/applicationActions.ts`).
 * `reload` refetches the application once an action is through.
 */
export function useDetailCommands(
  app: ApplicationRow | undefined,
  openTabs: OpenTabs,
  reload: () => Promise<void>,
  openReview: () => void,
): DetailCommands {
  const { settings, flushSettings } = useRunState();
  const { confirm } = useConfirm();
  const toast = useToast();
  // Kept per application: an action still running for one left behind (or its Undo,
  // pressed later from the status bar) never holds the next one's buttons.
  const [workingOn, setWorkingOn] = useState<ReadonlySet<string>>(() => new Set());
  const working = !!app && workingOn.has(app.source_job_id);
  const next = app ? nextAction(app, openTabs) : "view";
  const withNewFiles = !!app && next === "fill" && canContinueWithNewFiles(app, openTabs);

  async function run(work: () => Promise<unknown>, failure: string) {
    const id = app?.source_job_id ?? "";
    setWorkingOn((previous) => new Set(previous).add(id));
    try {
      await work();
    } catch (reason) {
      toast.error(failure, describe(reason).detail);
    } finally {
      setWorkingOn((previous) => {
        const left = new Set(previous);
        left.delete(id);
        return left;
      });
      await reload();
    }
  }

  async function fill(id: string, mode: "initial" | "continue" | "reopen") {
    if (!(await flushSettings())) {
      toast.error(
        "Your settings are not saved yet",
        "Nothing was started. Check the settings, then try again.",
      );
      return;
    }
    if (!(await resumeWarningsAccepted([id], confirm, toast))) return;
    await startApplyOperation(operationRequest(settings.apply, "fill", [id], mode));
  }

  function runNext() {
    if (!app || working) return;
    const id = app.source_job_id;
    if (next === "review") return openReview();
    if (next === "retry") return void run(() => retryApplication(id), "Could not retry");
    if (next === "continue" || withNewFiles)
      return void run(() => fill(id, "continue"), "Could not start");
    if (next === "fill") return void run(() => fill(id, "initial"), "Could not start");
    if (next !== "reopen") return;
    const tabOpen = !!app.fill?.browser_target_id && !isTabClosed(app, openTabs);
    void (
      tabOpen
        ? confirm({
            title: "Start this application over?",
            message: "Unsaved answers in the old browser tab may be lost.",
            confirmLabel: "Start over",
          })
        : Promise.resolve(true)
    ).then((ok) => {
      if (ok) void run(() => fill(id, "reopen"), "Could not start");
    });
  }

  async function mark(status: "submitted" | "skipped") {
    if (!app) return;
    const id = app.source_job_id;
    if (
      WORKING.has(app.status) &&
      !(await confirm({
        title: status === "submitted" ? "Mark submitted now?" : "Skip it now?",
        message: "A running Apply task has this application. It stops working on it first.",
        confirmLabel: status === "submitted" ? "Mark submitted" : "Skip",
      }))
    )
      return;
    await run(async () => {
      await setApplicationStatus(id, status);
      announceTabsChanged();
      // The mark moved it to Done; restoring it from there undoes the mark, as on Apply.
      const undo = () =>
        void run(async () => {
          const error = (await archiveApplications([id], false)).errors[id];
          if (error) throw new Error(error);
        }, "Could not undo");
      toast.success(`${app.company} marked ${status}`, "Moved to Done.", {
        label: "Undo",
        onClick: undo,
      });
    }, "Could not update the status");
  }

  const retryLabel = app ? retryAction(app) : null;
  const label =
    next === "continue" || withNewFiles
      ? "Continue fill"
      : next === "reopen"
        ? "Start over"
        : next === "fill"
          ? "Fill"
          : next === "retry"
            ? retryLabel
            : next === "review"
              ? "Review"
              : null;
  return {
    next,
    label,
    working,
    runNext,
    canMark: !!app && canMark(app),
    mark: (status) => void mark(status),
  };
}
