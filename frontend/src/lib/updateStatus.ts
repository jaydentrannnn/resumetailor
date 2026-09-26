import type { UpdateStatus } from "../api";

/** States in which an update is under way; the About card polls quickly through them. */
export const UPDATE_IN_PROGRESS = new Set<UpdateStatus["state"]>([
  "checking",
  "downloading",
  "ready",
  "waiting",
  "installing",
]);

/** Whether the header chip shows: an update is waiting for the user, or on its way in. */
export function updateChipVisible(status: UpdateStatus | null): boolean {
  if (!status?.supported) return false;
  return ["available", "downloading", "ready", "waiting", "installing"].includes(status.state);
}

/** "3 min ago" / "2 h ago" / "4 days ago" for the last check. */
export function sinceLabel(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const minutes = Math.max(0, Math.round((now - then) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** The one-line status under "Updates" in Settings → About. */
export function updateStatusLine(status: UpdateStatus, now: number = Date.now()): string {
  const version = status.available?.version;
  switch (status.state) {
    case "checking":
      return "Checking for updates…";
    case "available":
      return `Version ${version} is available.`;
    case "downloading":
      return status.pct != null
        ? `Downloading version ${version}… ${status.pct}%`
        : `Downloading version ${version}…`;
    case "ready":
      return `Version ${version} is downloaded. Installing…`;
    case "waiting":
      return `Version ${version} is downloaded. It installs when ${status.waiting_for ?? "the current task"} finishes.`;
    case "installing":
      return "Installing. ResumeTailor restarts in a moment…";
    case "error":
      return status.error ?? "The update failed.";
    case "up_to_date":
      return status.last_checked
        ? `Up to date · checked ${sinceLabel(status.last_checked, now)}`
        : "Up to date";
    default:
      return "Not checked yet. The app checks shortly after it starts, then twice a day.";
  }
}

/** Header chip text. */
export function updateChipLabel(status: UpdateStatus): string {
  return status.state === "available" ? "Update available" : "Updating…";
}
