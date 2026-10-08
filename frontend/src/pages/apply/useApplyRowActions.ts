import { useState } from "react";
import { useLocation } from "react-router-dom";
import {
  acknowledgeApplicationResume,
  archiveApplications,
  focusApplicationReviewTab,
  getApplication,
  retryApplication,
  setApplicationStatus,
  startApplyOperation,
  undoSubmitted,
  type ApplicationRow,
  type ApplyOperation,
  type ApplySettings,
} from "../../api";
import { rememberApplicationListScroll } from "../../lib/applicationNavigation";
import { isTabClosed, type OpenTabs } from "../../lib/applicationRows";
import { canRetailor } from "../../lib/applyPage";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import type { TableActions } from "./ApplicationsTable";
import type { FindOptions } from "./ProgressToolbar";
import type { ApplicationTableState } from "./useApplicationTable";

/**
 * Everything the page starts or changes on rows: Find / Prepare / Fill (with the resume
 * warning check), Reopen, Tailor again, Archive / Restore, Skip with Undo, Retry, Mark
 * and Undo submitted. `actions` is what each table row is handed.
 */
export function useApplyRowActions({
  apply,
  tables,
  openTabs,
  active,
  browserConnected,
  workspaceId,
  refresh,
  setOperation,
  wake,
  showError,
}: {
  apply: ApplySettings;
  tables: ApplicationTableState[];
  openTabs: OpenTabs;
  active: boolean;
  browserConnected: boolean;
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
      const { limit, dryRun, ageDays } = findOptions;
      setOperation(
        await startApplyOperation({
          action,
          application_ids: ids,
          fill_mode: mode,
          force_prepare: force,
          limit: Number(limit) > 0 ? Number(limit) : null,
          max_age_days: action === "find" ? ageDays : null,
          dry_run: action === "find" && dryRun,
          auto_submit: apply.auto_submit_enabled,
          blocker_mode: "continue",
          model_provider: apply.model_provider,
          model_name: apply.model_name,
        }),
      );
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
        for (const table of tables) table.deselect(result.updated);
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
        for (const table of tables) table.deselect(done);
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

  return { busy, findOptions, setFindOptions, actions };
}
