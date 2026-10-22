import type {
  ActivityBannerOptions,
  ApplyProgress,
  ApplySettings,
  GoalBannerOptions,
  PipelineBannerOptions,
  PipelineStage,
} from "../api";
import type { TimedItem } from "./applyProgress";

/**
 * The progress banners' options (Apply settings › Progress banner): defaults for what a
 * saved profile leaves out, the words each stage is shown with, and which times a banner
 * counts. Mirrors `GoalBannerOptions` & co. in `web/schemas.py`.
 */

export const STAGE_ORDER: PipelineStage[] = [
  "found",
  "screened_in",
  "tailored",
  "autofilled",
  "sent",
];

/** Column headings: "Screened in". */
export const STAGE_LABELS: Record<PipelineStage, string> = {
  found: "Found",
  screened_in: "Screened in",
  tailored: "Tailored",
  autofilled: "Autofilled",
  sent: "Sent",
};

/** In a sentence: "3 sent", "the postings screened in". */
export const STAGE_WORDS: Record<PipelineStage, string> = {
  found: "found",
  screened_in: "screened in",
  tailored: "tailored",
  autofilled: "autofilled",
  sent: "sent",
};

/** What to do next for a stage: "Send one today". */
export const STAGE_ACTIONS: Record<PipelineStage, string> = {
  found: "Find jobs",
  screened_in: "Screen one",
  tailored: "Tailor one",
  autofilled: "Autofill one",
  sent: "Send one",
};

export const GOAL_DEFAULTS: GoalBannerOptions = {
  counts: "sent",
  week_start: "monday",
  show_days: true,
  show_nudge: true,
  show_actions: true,
  compact: false,
};

export const ACTIVITY_DEFAULTS: ActivityBannerOptions = {
  range: "13w",
  start: null,
  end: null,
  counts: "sent",
  color: "green",
  show_stats: true,
  show_waiting: true,
  show_actions: true,
  compact: false,
};

export const PIPELINE_DEFAULTS: PipelineBannerOptions = {
  range: "all",
  start: null,
  end: null,
  stages: STAGE_ORDER,
  style: "cards",
  show_percent: true,
  show_drop: true,
  show_actions: true,
};

type Saved = Pick<ApplySettings, "goal_banner" | "activity_banner" | "pipeline_banner">;

export function goalOptions(apply: Saved): GoalBannerOptions {
  return { ...GOAL_DEFAULTS, ...apply.goal_banner };
}

export function activityOptions(apply: Saved): ActivityBannerOptions {
  return { ...ACTIVITY_DEFAULTS, ...apply.activity_banner };
}

/** The pipeline's options, its stages always in funnel order and at least two. */
export function pipelineOptions(apply: Saved): PipelineBannerOptions {
  const merged = { ...PIPELINE_DEFAULTS, ...apply.pipeline_banner };
  const stages = STAGE_ORDER.filter((stage) => merged.stages.includes(stage));
  return { ...merged, stages: stages.length >= 2 ? stages : STAGE_ORDER };
}

export const ACTIVITY_WEEKS: Record<Exclude<ActivityBannerOptions["range"], "custom">, number> = {
  "4w": 4,
  "13w": 13,
  "26w": 26,
  "52w": 52,
};

/** A custom range both ends of which are set, in order; otherwise null. */
export function customRange(options: {
  start: string | null;
  end: string | null;
}): { from: string; to: string } | null {
  const { start, end } = options;
  if (!start || !end) return null;
  return start <= end ? { from: start, to: end } : { from: end, to: start };
}

/** Each posting's time at `stage` (postings that never got there are left out). */
export function stageTimes(progress: ApplyProgress, stage: PipelineStage): TimedItem[] {
  const field = `${stage}_at` as const;
  if (!progress.postings?.length && stage === "sent") return progress.sent;
  return (progress.postings ?? []).flatMap((posting) => {
    const at = posting[field];
    return at ? [{ at, company: posting.company }] : [];
  });
}

const HEAT_MIX = [0, 25, 45, 70, 100];

/**
 * A heatmap cell's fill at shade 1–4 (shade 0 is the plain `bg-sunken` cell), always in
 * the app's accent color (the saved `activity_banner.color` is ignored).
 */
export function heatFill(level: number): string {
  return `color-mix(in srgb, var(--color-accent) ${HEAT_MIX[level]}%, transparent)`;
}

/**
 * Whether the heatmap should transpose (weekdays across, weeks down) so the long
 * edge is horizontal. Used when there are fewer than 7 weeks.
 */
export function heatmapAxes(weeks: number): { transpose: boolean } {
  return { transpose: weeks > 0 && weeks < 7 };
}
