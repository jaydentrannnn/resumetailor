import type { HiringProgress, OutcomeType } from "../api/outcomes";
import type { Tone } from "./tone";

export function runProgressPercent(processed: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((processed / total) * 100)));
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
  return (
    labels[status] ?? status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase())
  );
}

const statusTones: Record<string, Tone> = {
  tailoring: "live",
  filling: "live",
  ready: "ready",
  awaiting_review: "attention",
  awaiting_otp: "attention",
  needs_browser: "attention",
  submit_unconfirmed: "attention",
  tailor_failed: "failed",
  fill_failed: "failed",
  submitted: "done",
  interview: "done",
  rejected: "muted",
  ghosted: "muted",
};

/** Tone for a status chip; unknown and early-pipeline statuses stay neutral. */
export function applicationStatusTone(status: string): Tone {
  return statusTones[status] ?? "neutral";
}

/** What each recorded outcome is called in the Outcome tab. */
export const OUTCOME_LABELS: Record<OutcomeType, string> = {
  assessment: "Assessment or test",
  interview_invited: "Invited to interview",
  interview_scheduled: "Interview scheduled",
  interview_completed: "Interview done",
  offer: "Offer",
  hired: "Hired",
  offer_declined: "Declined the offer",
  rejected: "Rejected",
  withdrawn: "Withdrew",
  ghosted: "No reply",
  employer_timeline: "Employer gave a timeline",
  followup_drafted: "Follow-up drafted",
  followup_sent: "Follow-up sent",
};

/** Hiring filter options on the Done tab: key (closing outcome or stage) and label. */
export const HIRING_OPTIONS: [string, string][] = [
  ["applied", "Applied, no news"],
  ["assessment", "Assessment"],
  ["interview", "Interviewing"],
  ["offer", "Offer"],
  ["hired", "Hired"],
  ["rejected", "Rejected"],
  ["ghosted", "No reply"],
  ["withdrawn", "Withdrawn"],
  ["offer_declined", "Offer declined"],
];

/** Tone for a hiring-progress chip: further along reads stronger; closed reads muted. */
export function hiringTone(hiring: HiringProgress): Tone {
  if (hiring.closed) return "muted";
  if (hiring.stage === "offer" || hiring.stage === "hired") return "done";
  if (hiring.stage === "interview" || hiring.stage === "assessment") return "ready";
  return "neutral";
}
