/** What the Apply page last saw, for deciding which desktop notifications to raise. */
export interface ApplySnapshot {
  needsYou: number;
  /** "id:company" for each row waiting on an emailed code. */
  otp: string[];
  dailyRunning: boolean;
  dailySummary: Record<string, unknown> | null;
  /** The Apply tasks seen (several Prepare and Fill batches may run side by side). */
  operations: OperationSnapshot[];
}

export interface OperationSnapshot {
  id: string;
  state: string;
  action: string;
  readyForReview: number;
}

const ACTIVE = new Set(["queued", "running", "paused"]);
const num = (value: unknown) => (typeof value === "number" ? value : 0);

/**
 * Notifications for what changed between two polls. The first poll (`prev` null)
 * never notifies: opening the page is not news.
 */
export function applyNotifications(prev: ApplySnapshot | null, next: ApplySnapshot): string[] {
  if (!prev) return [];
  const out: string[] = [];
  const seenOtp = new Set(prev.otp);
  for (const entry of next.otp) {
    if (seenOtp.has(entry)) continue;
    const company = entry.slice(entry.indexOf(":") + 1) || "an application";
    out.push(`Enter the code sent to your email for ${company}`);
  }
  const newOtp = next.otp.filter((entry) => !seenOtp.has(entry)).length;
  if (next.needsYou > prev.needsYou && next.needsYou - prev.needsYou > newOtp)
    out.push(`${next.needsYou} application${next.needsYou === 1 ? " needs" : "s need"} you`);
  if (prev.dailyRunning && !next.dailyRunning) {
    const s = next.dailySummary ?? {};
    out.push(`Nightly run finished: ${num(s.new_rows)} found, ${num(s.tailored)} tailored`);
  }
  for (const before of prev.operations) {
    const after = next.operations.find((op) => op.id === before.id);
    if (after && ACTIVE.has(before.state) && !ACTIVE.has(after.state) && after.action !== "find") {
      const verb = after.action === "fill" ? "Filling" : "Tailoring";
      out.push(`${verb} finished: ${after.readyForReview} ready for you`);
    }
  }
  return out;
}

const KEY = "rt.apply.notify";

export function notifyPreference(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setNotifyPreference(on: boolean): void {
  try {
    window.localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* private mode: the toggle simply doesn't persist */
  }
}

export const notificationsSupported = () =>
  typeof window !== "undefined" && "Notification" in window;

/** Raise a system notification when the person turned them on and the OS allows it. */
export function notifyIfAllowed(body: string): void {
  if (!notifyPreference() || !notificationsSupported() || Notification.permission !== "granted")
    return;
  new Notification("ResumeTailor", { body, tag: body });
}
