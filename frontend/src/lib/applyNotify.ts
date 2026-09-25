/** What the Apply page last saw, for deciding which desktop notifications to raise. */
export interface ApplySnapshot {
  needsYou: number;
  /** "id:company" for each row waiting on an emailed code. */
  otp: string[];
  dailyRunning: boolean;
  dailySummary: Record<string, unknown> | null;
  operationId: string | null;
  operationState: string | null;
  operationAction: string | null;
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
    const parts = [`${num(s.new_rows)} found`, `${num(s.tailored)} tailored`];
    if (num(s.submitted)) parts.push(`${num(s.submitted)} submitted`);
    out.push(`Nightly run finished: ${parts.join(", ")}`);
  }
  if (
    prev.operationId &&
    prev.operationId === next.operationId &&
    ACTIVE.has(prev.operationState ?? "") &&
    !ACTIVE.has(next.operationState ?? "") &&
    next.operationAction !== "find"
  ) {
    const verb = next.operationAction === "fill" ? "Filling" : "Tailoring";
    out.push(`${verb} finished: ${next.readyForReview} ready for you`);
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
