/** What the Applications page's 2s poll saw: the latest Apply operation and the daily run. */
export type ApplyPollSnapshot = {
  operationId: string | null;
  state: string | null;
  dailyRunning: boolean;
};

const LIVE_STATES = new Set(["queued", "running", "paused"]);
/** Row statuses a background thread will still move on its own (a tailor retry, a fill). */
export const IN_FLIGHT_STATUSES = new Set(["tailoring", "filling"]);

export function pollSignature(snapshot: ApplyPollSnapshot): string {
  return `${snapshot.operationId ?? ""}:${snapshot.state ?? ""}:${snapshot.dailyRunning}`;
}

export function isApplyRunning(snapshot: ApplyPollSnapshot): boolean {
  return snapshot.dailyRunning || LIVE_STATES.has(snapshot.state ?? "");
}

/**
 * Reload the tables while work is running, while a visible row is still in flight, and
 * once whenever the latest operation or its state changed since the previous poll. The
 * last case catches an operation that started and finished between two polls.
 */
export function shouldRefreshTables(
  previous: string | null,
  snapshot: ApplyPollSnapshot,
  rowsInFlight: boolean,
): boolean {
  if (isApplyRunning(snapshot) || rowsInFlight) return true;
  return previous !== null && previous !== pollSignature(snapshot);
}
