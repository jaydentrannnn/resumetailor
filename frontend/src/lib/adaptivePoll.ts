/** Poll every 2 s while something is running, every 15 s when idle, never while hidden. */
export const BUSY_POLL_MS = 2000;
export const IDLE_POLL_MS = 15000;

/** Delay before the next poll, or null to wait for the tab to become visible again. */
export function nextPollDelay(busy: boolean, hidden: boolean): number | null {
  if (hidden) return null;
  return busy ? BUSY_POLL_MS : IDLE_POLL_MS;
}

type VisibilitySource = Pick<
  Document,
  "visibilityState" | "addEventListener" | "removeEventListener"
>;

/**
 * Run `tick` now and again after each `nextPollDelay`. `tick` resolves to whether
 * work is in flight. Hiding the tab stops the loop; showing it polls at once.
 * Returns `stop`, and `wake` to poll now (after the user starts something, so the
 * idle 15 s wait does not delay the first progress update).
 */
export function startAdaptivePoll(
  tick: () => Promise<boolean>,
  doc: VisibilitySource = document,
): { stop: () => void; wake: () => void } {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let running = false;
  let busy = true;

  const schedule = () => {
    if (stopped) return;
    clearTimeout(timer);
    const delay = nextPollDelay(busy, doc.visibilityState === "hidden");
    if (delay !== null) timer = setTimeout(() => void run(), delay);
  };
  const run = async () => {
    if (stopped || running) return;
    running = true;
    try {
      busy = await tick();
    } catch {
      // A failed poll keeps the last known state and tries again on schedule.
    } finally {
      running = false;
    }
    schedule();
  };
  const onVisibility = () => {
    if (doc.visibilityState === "visible") void run();
    else clearTimeout(timer);
  };

  doc.addEventListener("visibilitychange", onVisibility);
  void run();
  return {
    stop: () => {
      stopped = true;
      clearTimeout(timer);
      doc.removeEventListener("visibilitychange", onVisibility);
    },
    wake: () => void run(),
  };
}
