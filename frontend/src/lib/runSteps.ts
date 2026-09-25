import type { ProgressEvent, RunHistoryEntry } from "../api";

/**
 * The run's pipeline stages (`web/jobs.py` events) grouped into six steps a student
 * can follow. The fit loop repeats rewrite → render → measure, so progress is the
 * furthest step any event has reached and never moves backwards.
 */
export const RUN_STEPS = [
  { id: "read", label: "Reading the job", stages: ["extract"] },
  { id: "score", label: "Scoring your experience", stages: ["score"] },
  { id: "choose", label: "Choosing projects and coursework", stages: ["facets"] },
  { id: "rewrite", label: "Rewriting bullets", stages: ["rewrite"] },
  { id: "fit", label: "Fitting to the page", stages: ["fit", "render", "measure"] },
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
