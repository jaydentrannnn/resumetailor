import { useState } from "react";
import { useLocation } from "react-router-dom";
import {
  archiveApplications,
  focusApplicationReviewTab,
  retryApplication,
  setApplicationStatus,
  startApplyOperation,
  undoSubmitted,
  type ApplicationRow,
  type ApplyOperation,
  type ApplySettings,
} from "../../api";
import { operationRequest, resumeWarningsAccepted } from "../../lib/applicationActions";
import { rememberApplicationListScroll } from "../../lib/applicationNavigation";
import { isTabClosed, type OpenTabs } from "../../lib/applicationRows";
import { canRetailor } from "../../lib/applyPage";
import { describe } from "../../lib/errors";
import { announceTabsChanged } from "../../lib/tabsChanged";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import type { TableActions } from "./ApplicationsTable";
import type { FindOptions } from "./ProgressToolbar";
import type { ApplicationTableState } from "./useApplicationTable";

const TAB_CLOSES_NOTE = "Its tab closes in 30 s unless you keep it open.";

function hasOpenTab(row: ApplicationRow, openTabs: OpenTabs): boolean {
  return !!row.fill?.browser_target_id && !isTabClosed(row, openTabs);
}

function plural(n: number): string {
  return `${n} application${n === 1 ? "" : "s"}`;
}

/**
 * Everything the page starts or changes on rows: Find / Prepare / Fill (with the resume
 * warning check), Reopen, Tailor again, Archive / Restore, Skip and Mark submitted with
 * Undo, Retry, Undo submitted. `actions` is what each table row is handed; whatever acts
 * on rows clears them from the selection.
 */
export function useApplyRowActions({
  apply,
  flushSettings,
  tables,
  openTabs,
  active,
  exclusiveBusy,
  held,
  waiting,
  browserUsable,
  workspaceId,
  refresh,
  setOperation,
  wake,
  showError,
}: {
  apply: ApplySettings;
  /** Saves settings still waiting on the autosave; false when that failed. */
  flushSettings: () => Promise<boolean>;
  tables: ApplicationTableState[];
  openTabs: OpenTabs;
  active: boolean;
  exclusiveBusy: boolean;
  held: Set<string>;
  waiting: Set<string>;
  browserUsable: boolean;
  workspaceId: string;
  refresh: () => void;
  setOperation: (operation: ApplyOperation) => void;
  wake: () => void;
  showError: (title: string, reason: unknown) => void;
}) {
  const { confirm } = useConfirm();
  const toast = useToast();
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  const deselect = (ids: string[]) => {
    for (const table of tables) table.deselect(ids);
  };
  // The one-search-only options of the next Find jobs; none of them is saved.
  const [findOptions, setFindOptions] = useState<FindOptions>({
    limit: "",
    dryRun: false,
    ageDays: null,
  });

  async function start(
    action: "find" | "prepare" | "fill",
    ids: string[] = [],
    mode: "initial" | "continue" | "reopen" = "initial",
    force = false,
  ) {
    setBusy(true);
    try {
      // An operation captures the settings when it starts: never start on a stale copy
      // of what was just edited (audit #14).
      if (!(await flushSettings())) {
        toast.error(
          "Your settings are not saved yet",
          "Nothing was started. Check the settings drawer, then try again.",
        );
        return;
      }
      if (action === "fill" && !(await resumeWarningsAccepted(ids, confirm, toast))) return;
      const { limit, dryRun, ageDays } = findOptions;
      setOperation(
        await startApplyOperation({
          ...operationRequest(apply, action, ids, mode, force),
          limit: Number(limit) > 0 ? Number(limit) : null,
          max_age_days: action === "find" ? ageDays : null,
          dry_run: action === "find" && dryRun,
        }),
      );
      deselect(ids);
    } catch (reason) {
      showError("Could not start", reason);
    } finally {
      setBusy(false);
      wake();
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
      title: many ? `Start ${ids.length} applications over?` : "Start this application over?",
      message: many
        ? "Unsaved answers in tabs that are still open may be lost."
        : "Unsaved answers in the old browser tab may be lost.",
      confirmLabel: "Start over",
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
        deselect(result.updated);
        const title = `${plural(result.updated.length)} ${archived ? "moved to Done" : "restored"}`;
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

  /**
   * Mark the rows skipped or submitted in one go. Like Archive, Undo puts them back
   * instead of asking first; a bulk Mark submitted (a claim about each row) asks.
   */
  async function markAll(rows: ApplicationRow[], status: "submitted" | "skipped") {
    if (!rows.length) return;
    const submitted = status === "submitted";
    if (
      submitted &&
      rows.length > 1 &&
      !(await confirm({
        title: `Mark ${plural(rows.length)} submitted?`,
        message: "Only mark the applications you sent yourself. Each one moves to Done.",
        confirmLabel: "Mark submitted",
      }))
    )
      return;
    setBusy(true);
    try {
      const results = await Promise.allSettled(
        rows.map((row) => setApplicationStatus(row.source_job_id, status)),
      );
      const done: string[] = [];
      const failures: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled") done.push(rows[index].source_job_id);
        else failures.push(`${rows[index].company}: ${describe(result.reason).detail}`);
      });
      if (done.length) {
        deselect(done);
        // A skipped row's tab closes after a countdown; a submitted mark the app did not
        // see keeps its tab.
        const tabOpen =
          !submitted &&
          rows.some((row) => done.includes(row.source_job_id) && hasOpenTab(row, openTabs));
        const who = rows.length === 1 ? rows[0].company : plural(done.length);
        toast.success(
          `${who} marked ${status}`,
          tabOpen ? `Moved to Done. ${TAB_CLOSES_NOTE}` : "Moved to Done.",
          {
            label: "Undo",
            onClick: () => void unmark(done),
          },
        );
        announceTabsChanged();
      }
      if (failures.length)
        toast.error(`Some applications were not marked ${status}`, failures.join("; "));
      refresh();
    } finally {
      setBusy(false);
    }
  }

  /** One row from its menu or page. A row a running task holds is taken over: say so. */
  async function mark(row: ApplicationRow, status: "submitted" | "skipped") {
    if (
      held.has(row.source_job_id) &&
      !(await confirm({
        title: status === "submitted" ? "Mark submitted now?" : "Skip it now?",
        message: "A running Apply task has this application. It stops working on it first.",
        confirmLabel: status === "submitted" ? "Mark submitted" : "Skip",
      }))
    )
      return;
    await markAll([row], status);
  }

  /**
   * Undo of a Mark submitted or Skip. The mark moved each row to Done, and restoring a
   * row from Done is what undoes its mark (`store.set_archived`); undo-submitted is only
   * for a row already restored.
   */
  async function unmark(ids: string[]) {
    try {
      const result = await archiveApplications(ids, false);
      const failures = Object.entries(result.errors);
      if (failures.length)
        toast.error(
          "Some applications could not be restored",
          failures.map(([id, message]) => `${id}: ${message}`).join("; "),
        );
    } catch (reason) {
      showError("Could not undo the mark", reason);
    }
    refresh();
  }

  async function retry(row: ApplicationRow) {
    setBusy(true);
    try {
      await retryApplication(row.source_job_id);
      deselect([row.source_job_id]);
      refresh();
    } catch (reason) {
      showError("Could not retry", reason);
    } finally {
      setBusy(false);
    }
  }

  async function undo(row: ApplicationRow) {
    setBusy(true);
    try {
      await undoSubmitted(row.source_job_id);
      deselect([row.source_job_id]);
      refresh();
    } catch (reason) {
      showError("Could not move application back", reason);
    } finally {
      setBusy(false);
    }
  }

  function focusTabById(sourceJobId: string) {
    void focusApplicationReviewTab(sourceJobId).catch((reason) =>
      showError("Could not open the tab", reason),
    );
  }

  const actions: TableActions & { focusTabById: (sourceJobId: string) => void } = {
    busy,
    active,
    exclusiveBusy,
    held,
    waiting,
    browserUsable,
    openTabs,
    start: (action, ids, mode, force) => void start(action, ids, mode, force),
    reopen,
    retailor,
    move: (ids, archived) => void move(ids, archived),
    undo: (row) => void undo(row),
    retry: (row) => void retry(row),
    mark: (row, status) => void mark(row, status),
    skip: (rows) => void markAll(rows, "skipped"),
    markSubmitted: (rows) => void markAll(rows, "submitted"),
    focusTab: (row) => focusTabById(row.source_job_id),
    focusTabById,
    detail: (row, detailTab = "overview") => ({
      pathname: `/applications/${encodeURIComponent(row.source_job_id)}`,
      search: `?tab=${detailTab}`,
      state: { from: `${location.pathname}${location.search}`, archive: !!row.archived_at },
    }),
    rememberScroll: () => rememberApplicationListScroll(workspaceId),
  };

  return { busy, findOptions, setFindOptions, actions };
}
