import type { ProgressEvent, RunHistoryEntry } from "../api";

/**
 * The run's pipeline stages (`web/jobs.py` events) grouped into six steps a student
 * can follow. The fit loop repeats rewrite → render → measure, so progress is the
 * furthest step any event has reached and never moves backwards. `fit` is left out of
 * the fit step on purpose: `fit.py` emits "Selected N entries…" as `fit` *before* the
 * first rewrite, which would skip "Rewriting bullets"; a `render` always follows the
 * first rewrite. `start` (job picked up) belongs to no step.
 */
export const RUN_STEPS = [
  { id: "read", label: "Reading the job", stages: ["extract"] },
  { id: "score", label: "Scoring your experience", stages: ["score"] },
  { id: "choose", label: "Choosing projects and coursework", stages: ["facets"] },
  { id: "rewrite", label: "Rewriting bullets", stages: ["rewrite"] },
  { id: "fit", label: "Fitting to the page", stages: ["render", "measure"] },
  { id: "finish", label: "Finishing touches", stages: ["expand", "skills", "cover", "propose"] },
] as const;

export interface RunStepState {
  steps: { id: string; label: string }[];
  /** Index of the step in flight; `steps.length` once the run succeeded. */
  current: number;
  failed: number | null;
}

export function runSteps(
  events: ProgressEvent[],
  status: string | null,
  coverLetter: boolean,
): RunStepState {
  const steps = RUN_STEPS.map((s) => ({
    id: s.id,
    label: s.id === "finish" && coverLetter ? "Writing cover letter" : s.label,
  }));
  let current = 0;
  for (const ev of events) {
    const index = RUN_STEPS.findIndex((s) => (s.stages as readonly string[]).includes(ev.stage));
    if (index > current) current = index;
  }
  if (status === "succeeded") return { steps, current: steps.length, failed: null };
  return { steps, current, failed: status === "failed" ? current : null };
}

/** Median seconds of the last five successful runs, or null with fewer than two. */
export function typicalRunSeconds(history: RunHistoryEntry[]): number | null {
  const durations = history
    .filter((r) => r.status === "succeeded" && r.finished_at)
    .map((r) => (Date.parse(r.finished_at!) - Date.parse(r.created_at)) / 1000)
    .filter((s) => Number.isFinite(s) && s > 0)
    .slice(0, 5)
    .sort((a, b) => a - b);
  if (durations.length < 2) return null;
  const mid = Math.floor(durations.length / 2);
  return durations.length % 2 ? durations[mid] : (durations[mid - 1] + durations[mid]) / 2;
}

/** e.g. 45 -> "45s", 125 -> "2m 05s". */
export function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

/** "about 2 min" / "under a minute". */
export function formatTypical(seconds: number): string {
  if (seconds < 60) return "under a minute";
  return `about ${Math.round(seconds / 60)} min`;
}

/**
 * Per-step durations in ms, measured in the browser: `ProgressEvent` carries no
 * timestamps, so `marks[i]` is when this tab first saw step `i` become current
 * (`marks[steps.length]` when it saw the run succeed). A finished step lasts until the
 * next marked step; the step in flight lasts until `now` (the caller freezes `now` when
 * the run stops). Null for steps not reached, skipped, or begun before this tab started
 * watching (a reload that re-attaches mid-run).
 */
export function stepDurations(
  marks: Readonly<Record<number, number>>,
  current: number,
  total: number,
  now: number,
): (number | null)[] {
  return Array.from({ length: total }, (_, index) => {
    const start = marks[index];
    if (start == null || index > current) return null;
    if (index === current) return Math.max(0, now - start);
    for (let next = index + 1; next <= total; next++) {
      if (marks[next] != null) return Math.max(0, marks[next] - start);
    }
    return null;
  });
}

/** e.g. 3140 -> "3.1s", 41000 -> "41s", 125000 -> "2m 05s". */
export function formatStepDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  return formatElapsed(Math.round(seconds));
}
