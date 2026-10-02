import type {
  ApplicationRow,
  ApplyOperation,
  ApplySettings,
  InFlightItem,
  JobStatus,
} from "../api";
import { runProgress } from "./runProgress";
import { canFillAfterReview } from "./applicationRows";
import { runSteps } from "./runSteps";

/** Where the job sources are managed (per profile); opened from Apply settings and Find jobs. */
export const SOURCES_PATH = "/applications/sources";

/** The Apply page's tabs, in the URL as `?tab=`. */
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
/** Statuses where a tailor or fill is in flight, or a submit may have gone through:
 * tailoring again there would race the run or replace files already sent. */
const NO_RETAILOR = new Set(["tailoring", "filling", "submit_unconfirmed"]);

/**
 * Whether a row can have its files tailored again: any row with a tailor run that is
 * not finished (submitted, skipped, ...) and has nothing in flight. Files that are
 * already fine are re-made too — the point is to pick up a better tailoring.
 */
export function canRetailor(row: { job_id: string | null; status: string }): boolean {
  return !!row.job_id && !TERMINAL_STATUSES.has(row.status) && !NO_RETAILOR.has(row.status);
}

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
  taleo: "Taleo",
  successfactors: "SuccessFactors",
  jobvite: "Jobvite",
  bamboohr: "BambooHR",
  linkedin: "LinkedIn",
  indeed: "Indeed",
  handshake: "Handshake",
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
    if (row.status === "ready" && canFillAfterReview(row)) continue;
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

/** Which posting-age segment a day count selects; anything but 1 or 7 is a custom window. */
export function ageChoice(days: number): "1" | "7" | "custom" {
  if (days === 1) return "1";
  if (days === 7) return "7";
  return "custom";
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
  if ((op.in_flight?.length ?? 0) > 1) {
    return `${op.action === "prepare" ? "Preparing" : "Filling"} ${op.in_flight!.length} at once`;
  }
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
/**
 * Time left, from the average time per item so far. ``done`` counts the item in flight
 * by its fraction (`itemProgress`), so the estimate appears during the first item.
 */
export function operationEtaSeconds(
  op: ApplyOperation,
  nowMs: number,
  done: number = op.processed,
): number | null {
  if (!["running"].includes(op.state) || op.total <= 0 || done <= 0.05) return null;
  const started = Date.parse(op.started_at);
  if (!Number.isFinite(started)) return null;
  const perItem = (nowMs - started) / 1000 / done;
  return Math.max(0, Math.round(perItem * (op.total - done)));
}

/** Pages a Workday fill typically walks; only an estimate (tenants differ). */
const TYPICAL_FILL_PAGES = 9;

export type ItemProgress = {
  /** 0 to just under 1: how far the item in flight is. */
  fraction: number;
  /** "Tailoring, step 4 of 6 (Rewriting bullets)" / "Filling, page 3 (estimate)". */
  detail: string;
  /** The fraction is a guess (a fill's page count is unknown in advance). */
  estimate: boolean;
};

/**
 * Progress inside the application being worked on. Prepare reads the tailor job's own
 * stage events (the Tailor page's six steps); Fill has no known length, so it counts
 * form pages against a typical nine, or elapsed time against the item's deadline,
 * and says it is an estimate. Null when nothing is known.
 */
export function itemProgress(
  op: ApplyOperation,
  job: JobStatus | null,
  nowMs: number,
  inFlight?: InFlightItem,
): ItemProgress | null {
  if (
    !["running", "paused"].includes(op.state) ||
    !(inFlight?.application_id || op.current_application_id)
  )
    return null;
  if (op.action === "prepare") {
    const jobId = inFlight?.job_id ?? op.current_job_id;
    if (!job || !jobId || job.job_id !== jobId) return null;
    const bar = runProgress(job.events, job.status, true);
    const steps = runSteps(job.events, job.status, false);
    const step = Math.min(steps.current, steps.steps.length - 1);
    return {
      fraction: Math.min(0.99, Math.max(0, bar.value)),
      detail: `Tailoring, step ${step + 1} of ${steps.steps.length} (${steps.steps[step].label})`,
      estimate: false,
    };
  }
  if (op.action === "fill") {
    const step = inFlight?.step ?? op.current_step;
    if (step > 0) {
      return {
        fraction: Math.min(step / TYPICAL_FILL_PAGES, 0.9),
        detail: `Filling, page ${step} (estimate)`,
        estimate: true,
      };
    }
    const started = Date.parse(inFlight?.started_at ?? op.application_started_at ?? "");
    const deadline = Date.parse(inFlight?.deadline_at ?? op.application_deadline_at ?? "");
    if (!Number.isFinite(started) || !Number.isFinite(deadline) || deadline <= started) return null;
    return {
      fraction: Math.min(0.9, Math.max(0, (nowMs - started) / (deadline - started))),
      detail: "Filling (estimate)",
      estimate: true,
    };
  }
  return null;
}

/** "about 4 min" / "under a minute". */
export function formatEta(seconds: number): string {
  if (seconds < 60) return "under a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `about ${hours} h ${minutes % 60} min`;
}

type AutoSubmitCaps = Pick<
  ApplySettings,
  | "auto_submit_enabled"
  | "auto_submit_max_per_run"
  | "auto_submit_max_per_day"
  | "auto_submit_max_per_company_per_day"
>;

/**
 * The three auto-submit caps as one sentence. The per-run cap applies to the nightly
 * run's unattended submits; the 24-hour caps to every automatic submit.
 */
export function autoSubmitSummary(caps: AutoSubmitCaps): string {
  if (!caps.auto_submit_enabled) return "Auto-submit is off: every application waits for you.";
  if (caps.auto_submit_max_per_day <= 0 || caps.auto_submit_max_per_company_per_day <= 0)
    return "A limit is 0, so nothing is submitted automatically.";
  const nightly =
    caps.auto_submit_max_per_run > 0
      ? `Nightly run: up to ${caps.auto_submit_max_per_run}`
      : "Nightly run: none";
  return `${nightly} · no more than ${caps.auto_submit_max_per_day} a day · no more than ${caps.auto_submit_max_per_company_per_day} per company.`;
}

/** "2:00 AM" for a stored "02:00" (the viewer's locale); the raw value if unparseable. */
export function scheduleTimeLabel(value: string): string {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return value;
  const date = new Date(2000, 0, 1, Number(match[1]), Number(match[2]));
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** The Apply page header's nightly-run chip text. */
export function nightlyRunLabel(
  settings: Pick<ApplySettings, "enabled" | "schedule_time">,
): string {
  return settings.enabled
    ? `Nightly run: on · ${scheduleTimeLabel(settings.schedule_time)}`
    : "Nightly run: off";
}
