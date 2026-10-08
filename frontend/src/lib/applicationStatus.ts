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
  ready: "neutral",
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
