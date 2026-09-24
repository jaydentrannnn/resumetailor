export function runProgressPercent(processed: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round(processed / total * 100)));
}

export function applicationStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: "Ready", tailoring: "Preparing", submitted: "Submitted", discovered: "Discovered",
    needs_browser: "Browser needed", awaiting_review: "Needs review", awaiting_otp: "Verification code needed",
    fill_failed: "Fill failed", tailor_failed: "Preparation failed", submit_unconfirmed: "Submission unconfirmed",
    screened_out: "Screened out",
  };
  return labels[status] ?? status.replaceAll("_", " ").replace(/^./, letter => letter.toUpperCase());
}

export type StatusTone = "neutral" | "info" | "accent" | "warn" | "danger" | "success" | "muted";

const statusTones: Record<string, StatusTone> = {
  tailoring: "info", filling: "info",
  ready: "accent",
  awaiting_review: "warn", awaiting_otp: "warn", needs_browser: "warn", submit_unconfirmed: "warn",
  tailor_failed: "danger", fill_failed: "danger",
  submitted: "success", interview: "success",
  rejected: "muted", ghosted: "muted",
};

/** Colour group for a status pill; unknown and early-pipeline statuses stay neutral. */
export function applicationStatusTone(status: string): StatusTone {
  return statusTones[status] ?? "neutral";
}

export const statusToneClass: Record<StatusTone, string> = {
  neutral: "bg-paper text-ink border border-line",
  info: "bg-info-soft text-info",
  accent: "bg-accent-soft text-accent",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
  success: "bg-success-soft text-success",
  muted: "bg-paper text-ink-muted",
};
