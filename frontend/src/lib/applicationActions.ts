import {
  acknowledgeApplicationResume,
  getApplication,
  type ApplicationRow,
  type ApplySettings,
  type startApplyOperation,
} from "../api";
import {
  canContinueFill,
  canFillAfterReview,
  canReopenFill,
  isTabClosed,
  retryShortLabel,
  type OpenTabs,
} from "./applicationRows";
import { REVIEW_STATUSES, TERMINAL_STATUSES, readyBlockLabel } from "./applyPage";
import type { ToastApi } from "./toast";

/**
 * What can be done to an application row, shared by the Apply table, its selection bar
 * and the application's detail header, so the three always offer the same next step.
 */
export type NextAction = "continue" | "reopen" | "review" | "fill" | "retry" | "view";

/** The short Retry label when retrying is the row's next step, else null. */
export function retryAction(row: ApplicationRow, archived = !!row.archived_at): string | null {
  return !archived &&
    !TERMINAL_STATUSES.has(row.status) &&
    !REVIEW_STATUSES.has(row.status) &&
    row.retry_kind
    ? retryShortLabel(row.retry_kind, row.status)
    : null;
}

/** The row's next step. A ready row the server won't fill ("Check resume") is a Review. */
export function nextAction(
  row: ApplicationRow,
  openTabs: OpenTabs,
  archived = !!row.archived_at,
): NextAction {
  if (archived || TERMINAL_STATUSES.has(row.status)) return "view";
  if (REVIEW_STATUSES.has(row.status)) {
    if (canContinueFill(row, openTabs)) return "continue";
    return isTabClosed(row, openTabs) && canReopenFill(row) ? "reopen" : "review";
  }
  if (row.status === "ready" && canFillAfterReview(row)) return "fill";
  if (readyBlockLabel(row)) return "review";
  return retryAction(row, archived) ? "retry" : "view";
}

/** Mark submitted and Skip apply to every unfinished row, a filling one included: the
 * server stops the task working on it first (audit #2). */
export function canMark(row: ApplicationRow): boolean {
  return !row.archived_at && !TERMINAL_STATUSES.has(row.status);
}

/** The checked rows a bulk Mark submitted or Skip acts on: unfinished rows no running
 * task holds (one row at a time, from its menu, can still take over a held row). */
export function bulkMarkable(rows: ApplicationRow[], held: Set<string>): ApplicationRow[] {
  return rows.filter((row) => canMark(row) && !held.has(row.source_job_id));
}

type Confirm = (options: { title: string; message: string; confirmLabel?: string }) => Promise<boolean>;

/**
 * Before a Fill: false (with a toast) when a flagged resume could not be verified, or when
 * its warnings were shown and not accepted; accepted warnings are acknowledged.
 */
export async function resumeWarningsAccepted(
  ids: string[],
  confirm: Confirm,
  toast: ToastApi,
): Promise<boolean> {
  const current = await Promise.all(ids.map((id) => getApplication(id)));
  const flagged = current.filter((item) => item.application.resume_review?.required);
  if (flagged.some((item) => !item.application.resume_review?.quality.verified)) {
    toast.error(
      "Prepare these resumes again",
      "Resume quality could not be verified. Open the application details to review.",
    );
    return false;
  }
  if (!flagged.length) return true;
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
  if (!accepted) return false;
  await Promise.all(
    flagged.map(({ application: app }) =>
      acknowledgeApplicationResume(app.source_job_id, app.resume_review!.revision),
    ),
  );
  return true;
}

/** The start request for Prepare or Fill on `ids`, with the saved Fill settings. */
export function operationRequest(
  apply: ApplySettings,
  action: "find" | "prepare" | "fill",
  ids: string[],
  mode: "initial" | "continue" | "reopen" = "initial",
  force = false,
): Parameters<typeof startApplyOperation>[0] {
  return {
    action,
    application_ids: ids,
    fill_mode: mode,
    force_prepare: force,
    auto_submit: apply.auto_submit_enabled,
    blocker_mode: "continue",
    model_provider: apply.model_provider,
    model_name: apply.model_name || "default",
    model_selection: apply.model_selection,
  };
}
