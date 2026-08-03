import type { ProgressEvent } from "../api";

/**
 * Turns the pipeline's stage events into a progress bar.
 *
 * `events.py` emits named stages precisely so a UI can drive a bar off structure
 * rather than scrape prose, but the run is only *partly* determinate: the fit loop
 * (rewrite → render → measure → fit) repeats an unknown number of times, bounded by
 * `MAX_SHORTEN_ATTEMPTS` / `MAX_GROW_ATTEMPTS`. So each stage owns a fixed band of
 * the bar, and the fit band creeps per measured iteration without ever leaving its
 * band. The result is honest: it never claims to know how long the loop will run.
 *
 * Progress is derived from the *furthest* band any event has reached, not from the
 * latest event, so it can never rewind — `web/jobs.py` emits a late `render` event
 * when PDF preview fails, which would otherwise drag the bar back out of `expand`.
 */

/** Pipeline order, matching `web/jobs.py`: extract → score → facets → fit → expand. */
const BANDS: { stages: string[]; from: number; to: number }[] = [
  { stages: ["extract"], from: 0.04, to: 0.16 },
  { stages: ["score"], from: 0.16, to: 0.3 },
  { stages: ["facets"], from: 0.3, to: 0.42 },
  // One band for the whole loop — its four stages interleave and repeat, so they
  // cannot be ordered against each other the way the single-shot stages can.
  { stages: ["fit", "rewrite", "render", "measure"], from: 0.42, to: 0.88 },
  { stages: ["expand"], from: 0.88, to: 0.97 },
];

/** Share of the fit band's remainder each completed iteration closes (asymptotic). */
const FIT_ITERATION_DECAY = 0.45;

const LABELS: Record<string, string> = {
  extract: "Reading the posting",
  score: "Scoring bullets",
  facets: "Selecting tech & coursework",
  fit: "Fitting to the page",
  rewrite: "Rewriting bullets",
  render: "Rendering draft",
  measure: "Measuring pages",
  expand: "Expanding experience",
};

export type RunProgress = {
  /** 0-1, monotonic across a single run. */
  value: number;
  /** True while the run has started but no stage event has arrived yet. */
  indeterminate: boolean;
  /** Short label for the phase currently in flight. */
  label: string;
};

function bandOf(stage: string): number {
  return BANDS.findIndex((b) => b.stages.includes(stage));
}

/**
 * Progress for a run, from the events seen so far plus the job's status.
 *
 * A finished run always reads 100% regardless of which stage it stopped on —
 * expansion is optional, and skipping it must not leave the bar stranded short.
 */
export function runProgress(
  events: ProgressEvent[],
  status: string | null,
  busy: boolean,
): RunProgress {
  if (status === "succeeded" || status === "failed") {
    return {
      value: 1,
      indeterminate: false,
      label: status === "failed" ? "Failed" : "Done",
    };
  }

  const reached = Math.max(-1, ...events.map((e) => bandOf(e.stage)));
  if (reached === -1) {
    // No recognised stage yet: either nothing has arrived, or only stages this build
    // does not know about. Show motion without committing to a position.
    return {
      value: busy ? 0.02 : 0,
      indeterminate: busy,
      label: events.length ? events[events.length - 1].stage : status === "queued" ? "Queued" : "Starting",
    };
  }

  const band = BANDS[reached];
  let fraction: number;
  if (band.stages.length === 1) {
    // Single-shot stage: two events (start, then result) or one (cache hit). Sit at
    // the midpoint while it is in flight rather than pretending to know sub-progress.
    fraction = 0.5;
  } else {
    // Fit loop: each completed measure is one iteration. Approach the band's end
    // without reaching it, so even a long loop keeps reading as progress.
    const iterations = events.filter((e) => e.stage === "measure").length;
    fraction = 1 - Math.pow(FIT_ITERATION_DECAY, iterations + 1);
  }

  const last = events[events.length - 1];
  return {
    value: band.from + (band.to - band.from) * fraction,
    indeterminate: false,
    label: LABELS[last.stage] ?? LABELS[band.stages[0]] ?? band.stages[0],
  };
}
