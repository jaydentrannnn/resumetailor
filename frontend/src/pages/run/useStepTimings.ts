import { useEffect, useState } from "react";
import { formatStepDuration, stepDurations } from "../../lib/runSteps";

type Timing = {
  key: string | null;
  /** Browser time each step was first seen current; `total` = the run succeeded. */
  marks: Record<number, number>;
  /** When the run stopped (done, failed, cancelled), so the last step stops ticking. */
  stoppedAt: number | null;
};

/**
 * Mono duration labels for the run's steps, measured in this tab. Marks reset when
 * `runKey` (the job id) changes; a run loaded from history was never watched, so it has
 * no marks and every label is undefined. The step in flight ticks once a second.
 */
export function useStepTimings(
  current: number,
  total: number,
  runKey: string | null,
  active: boolean,
): (string | undefined)[] {
  const [timing, setTiming] = useState<Timing>({ key: runKey, marks: {}, stoppedAt: null });
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setTiming((prev) => {
      const base: Timing = prev.key === runKey ? prev : { key: runKey, marks: {}, stoppedAt: null };
      const watched = Object.keys(base.marks).length > 0;
      if (!active && !watched) return base;
      const at = Date.now();
      const marks = base.marks[current] == null ? { ...base.marks, [current]: at } : base.marks;
      const stoppedAt = active ? null : (base.stoppedAt ?? at);
      if (marks === base.marks && stoppedAt === base.stoppedAt) return base;
      return { key: runKey, marks, stoppedAt };
    });
  }, [runKey, current, active]);

  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);

  // Until the effect catches up with a new job, show nothing rather than the old marks.
  const marks = timing.key === runKey ? timing.marks : {};
  const end = timing.stoppedAt ?? now;
  return stepDurations(marks, current, total, end).map((ms) =>
    ms == null ? undefined : formatStepDuration(ms),
  );
}
