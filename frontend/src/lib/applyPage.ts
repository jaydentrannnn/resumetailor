import type { ApplicationRow, ApplyOperation } from "../api";

/** The Apply page's three tabs, in the URL as `?tab=`. */
export type ApplyTab = "needs" | "progress" | "done";

export const REVIEW_STATUSES = new Set([
  "awaiting_review",
  "awaiting_otp",
  "submit_unconfirmed",
  "fill_failed",
]);
export const TERMINAL_STATUSES = new Set([
  "submitted",
  "interview",
  "rejected",
  "ghosted",
  "skipped",
]);
const PRE_READY = new Set([
  "discovered",
  "jd_fetched",
  "needs_browser",
  "screened_in",
  "screened_out",
  "tailoring",
  "tailor_failed",
]);

/** The tab named in the URL, else "Needs you" when anything is waiting, else "In progress". */
export function resolveApplyTab(param: string | null, needsYou: number | null): ApplyTab {
  if (param === "needs" || param === "progress" || param === "done") return param;
  return needsYou ? "needs" : "progress";
}

export interface ReviewReason {
  /** Primary text for the "Why it needs you" column. */
  why: string;
  /** Short, specific label for the row's action button (fits the action column). */
  action: string;
  /** Profile field to fill in, when a blank profile fact is the blocker. */
  profilePath?: string;
}

const SIGN_IN = /sign[ -]?in|log[ -]?in|password|account|create an account/i;
const CAPTCHA = /captcha|robot|human verification/i;
const ATS_NAMES: Record<string, string> = {
  workday: "Workday",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  icims: "iCIMS",
  smartrecruiters: "SmartRecruiters",
  oracle: "Oracle",
};

/**
 * What a "Needs you" row is waiting on, in the applicant's words, with a specific
 * next step. Built from `review_summary` (server, `store.review_summary`) plus the
 * fill's hand-off details.
 */
export function reviewReason(row: ApplicationRow): ReviewReason {
  const fill = row.fill ?? null;
  const handoff = fill?.handoff_reason ?? "";
  const summary = row.review_summary ?? "";
  if (row.status === "awaiting_otp")
    return {
      why: row.otp_prompt || "Enter the code the site emailed you",
      action: "Enter code",
    };
  if (row.status === "submit_unconfirmed")
    return { why: "Check whether the application went through", action: "Confirm" };
  if (CAPTCHA.test(handoff)) return { why: "Solve the CAPTCHA in the tab", action: "CAPTCHA" };
  if (summary === "Sign-in needed" || SIGN_IN.test(handoff)) {
    const site = ATS_NAMES[row.ats] ?? "the job site";
    return { why: `Sign in to ${site}`, action: "Sign in" };
  }
  const blankProfile = (fill?.missing_profile ?? []).filter((field) => !field.answered);
  if (blankProfile.length > 0)
    return {
      why:
        blankProfile.length === 1
          ? `Add "${blankProfile[0].field_label}" to your profile`
          : `Add ${blankProfile.length} answers to your profile`,
      action: "Profile",
      profilePath: blankProfile[0].path,
    };
  if (row.status === "fill_failed")
    return { why: row.error || fill?.error || "The fill stopped with an error", action: "Details" };
  if (summary === "Ready to submit")
    return { why: "Final check before submitting", action: "Final check" };
  if (summary && summary !== "Check the form" && summary !== "Fill failed") {
    const more = summary.match(/^(.*) \+(\d+)$/);
    const count = more ? Number(more[2]) + 1 : 1;
    return {
      why:
        count === 1
          ? `Answer "${summary}"`
          : `${count} questions left blank, starting with "${more![1]}"`,
      action: count === 1 ? "Answer" : `Answer ${count}`,
    };
  }
  return { why: "Check the form before it is submitted", action: "Review" };
}

/** Why some selected rows can't be filled, e.g. "2 selected can't be filled yet: not tailored". */
export function fillBlockers(rows: ApplicationRow[]): string | null {
  const reasons = new Map<string, number>();
  const add = (reason: string) => reasons.set(reason, (reasons.get(reason) ?? 0) + 1);
  for (const row of rows) {
    if (row.status === "ready" && row.preparation_eligible !== false) continue;
    if (TERMINAL_STATUSES.has(row.status)) add("already finished");
    else if (row.status === "ready") add("files are out of date");
    else if (row.status === "filling") add("being filled now");
    else if (PRE_READY.has(row.status)) add("not tailored");
    else add("waiting on you");
  }
  const blocked = [...reasons.values()].reduce((a, b) => a + b, 0);
  if (blocked === 0) return null;
  const detail = [...reasons.entries()]
    .map(([reason, n]) => (reasons.size > 1 ? `${n} ${reason}` : reason))
    .join(", ");
  return `${blocked} selected can't be filled yet: ${detail}`;
}

/** The submission-cap field's meaning; 0 must never read as "unlimited". */
export function autoSubmitCapLabel(cap: number): string {
  if (!cap || cap <= 0) return "No auto-submits";
  return `At most ${cap} per run`;
}

const ACTION_VERB: Record<string, string> = {
  find: "Finding jobs",
  prepare: "Tailoring",
  fill: "Filling",
  inspect: "Checking",
  correct: "Correcting",
};

/** "Tailoring 3 of 12 · Acme" for the operation banner. */
export function operationHeadline(op: ApplyOperation): string {
  const verb = ACTION_VERB[op.action] ?? op.action;
  if (op.state === "paused") return `Paused · ${verb.toLowerCase()}`;
  if (!["queued", "running"].includes(op.state)) {
    const done = op.state.replaceAll("_", " ");
    return `${verb} ${done}`;
  }
  const position = op.total > 0 ? ` ${Math.min(op.processed + 1, op.total)} of ${op.total}` : "";
  const label = op.current_label ? ` · ${op.current_label}` : "";
  return `${verb}${position}${label}`;
}

/** Remaining time from the average per-item time so far; null until one item is done. */
export function operationEtaSeconds(op: ApplyOperation, nowMs: number): number | null {
  if (!["running"].includes(op.state) || op.total <= 0 || op.processed <= 0) return null;
  const started = Date.parse(op.started_at);
  if (!Number.isFinite(started)) return null;
  const perItem = (nowMs - started) / 1000 / op.processed;
  return Math.max(0, Math.round(perItem * (op.total - op.processed)));
}

/** "about 4 min" / "under a minute". */
export function formatEta(seconds: number): string {
  if (seconds < 60) return "under a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `about ${hours} h ${minutes % 60} min`;
}
