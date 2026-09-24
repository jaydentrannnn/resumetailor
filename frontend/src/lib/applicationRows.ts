import type { ApplicationRow } from "../api";

/** Pure helpers for Applications-table rows, driven by server-computed fields. */

/**
 * Whether a row's funnel is closed (submitted, interview, rejected, ghosted, skipped).
 *
 * Read from the server's own `preparation_reasons` (`store.TERMINAL_STATUSES` via
 * `preparation.check`) rather than a client-side copy that can drift.
 */
export function isTerminalRow(row: Pick<ApplicationRow, "preparation_reasons">): boolean {
  return (row.preparation_reasons ?? []).includes("terminal_application");
}

/** Button text for a row's server-reported retry (`daily.retry_kind`). */
export function retryLabel(kind: NonNullable<ApplicationRow["retry_kind"]>, status: string): string {
  if (kind === "prefilter") return "↻ Re-check eligibility";
  if (kind === "tailor") return "↻ Retry tailoring";
  return status === "discovered" ? "⚡ Fetch JD" : "↻ Refetch JD";
}

/** One-word label for the table's fixed-width action button; `retryLabel` is the full text. */
export function retryShortLabel(kind: NonNullable<ApplicationRow["retry_kind"]>, status: string): string {
  if (kind === "prefilter") return "Recheck";
  if (kind === "tailor") return "Retry";
  return status === "discovered" ? "Fetch JD" : "Refetch";
}

/** Tooltip for the same button — says what the retry does, never more. */
export function retryTitle(kind: NonNullable<ApplicationRow["retry_kind"]>): string {
  if (kind === "prefilter") return "Re-run the eligibility prefilter against the saved job description";
  if (kind === "tailor") return "Queue tailoring again; the row updates when it finishes";
  return "Fetch the job description";
}

/** Statuses where a fill stopped for the applicant and left its tab open. */
const CONTINUABLE = new Set(["awaiting_review", "awaiting_otp", "fill_failed"]);

/**
 * Whether Fill can resume in the row's retained browser tab: the fill stopped for input
 * (or failed mid-way) and the server kept that tab's target id.
 */
export function canContinueFill(
  row: Pick<ApplicationRow, "status" | "archived_at" | "preparation_eligible" | "fill">,
): boolean {
  return !!row.fill?.browser_target_id && !row.archived_at && row.preparation_eligible !== false
    && CONTINUABLE.has(row.status);
}
