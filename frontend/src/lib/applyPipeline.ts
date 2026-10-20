import type { ApplyProgress, PipelineBannerOptions, PipelineStage } from "../api";
import { addDays, dayKey, shortDate, weekStart } from "./applyProgress";
import { STAGE_LABELS, STAGE_WORDS, customRange } from "./progressOptions";

/**
 * The pipeline banner: how far the postings found in a date range got, over the stages
 * the applicant chose. Dates are the applicant's own days.
 */

export type StageCounts = Record<PipelineStage, number>;

export type PipelineStep = {
  stage: PipelineStage;
  label: string;
  count: number;
  /** Percent of the first stage shown. */
  share: number;
  /** "27% of found": against the stage shown before it. */
  rate: string;
};

/** The days a range covers (both ends included), and how it reads; null = all time. */
export function pipelineWindow(
  options: Pick<PipelineBannerOptions, "range" | "start" | "end">,
  now: Date,
): { from: string | null; to: string | null; label: string } {
  const today = dayKey(now);
  switch (options.range) {
    case "week":
      return { from: dayKey(weekStart(now)), to: today, label: "this week" };
    case "month":
      return {
        from: dayKey(new Date(now.getFullYear(), now.getMonth(), 1)),
        to: today,
        label: "this month",
      };
    case "30d":
      return { from: dayKey(addDays(now, -29)), to: today, label: "last 30 days" };
    case "custom": {
      const range = customRange(options);
      if (range) return { ...range, label: `${shortDate(range.from)} – ${shortDate(range.to)}` };
      return { from: null, to: null, label: "all time" };
    }
    default:
      return { from: null, to: null, label: "all time" };
  }
}

/** How many of the postings found between `from` and `to` reached each stage. */
export function stageCounts(
  progress: ApplyProgress,
  window: { from: string | null; to: string | null },
): StageCounts {
  const counts: StageCounts = { found: 0, screened_in: 0, tailored: 0, autofilled: 0, sent: 0 };
  const all = !window.from && !window.to;
  if (all && !progress.postings?.length) {
    return {
      found: progress.found,
      screened_in: progress.screened_in,
      tailored: progress.tailored,
      autofilled: progress.autofilled,
      sent: progress.sent_total,
    };
  }
  for (const posting of progress.postings ?? []) {
    if (!all) {
      const found = posting.found_at ? new Date(posting.found_at) : null;
      if (!found || Number.isNaN(found.getTime())) continue;
      const key = dayKey(found);
      if ((window.from && key < window.from) || (window.to && key > window.to)) continue;
    }
    counts.found += 1;
    if (posting.screened_in_at) counts.screened_in += 1;
    if (posting.tailored_at) counts.tailored += 1;
    if (posting.autofilled_at) counts.autofilled += 1;
    if (posting.sent_at) counts.sent += 1;
  }
  return counts;
}

const pct = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

/** The chosen stages in order, each as a share of the first and of the one before. */
export function pipelineSteps(counts: StageCounts, stages: PipelineStage[]): PipelineStep[] {
  const first = counts[stages[0]];
  return stages.map((stage, i) => {
    const before = i > 0 ? stages[i - 1] : null;
    return {
      stage,
      label: STAGE_LABELS[stage],
      count: counts[stage],
      share: pct(counts[stage], first),
      rate:
        before === null
          ? stage === "found"
            ? "every posting your sources found"
            : `of the postings ${STAGE_WORDS[stage]}`
          : `${pct(counts[stage], counts[before])}% of ${STAGE_WORDS[before]}`,
    };
  });
}

/** "14% of the postings found were sent." */
export function pipelineHeadline(steps: PipelineStep[]): string {
  const first = steps[0];
  const last = steps[steps.length - 1];
  return `${last.share}% of the postings ${STAGE_WORDS[first.stage]} were ${STAGE_WORDS[last.stage]}.`;
}

/**
 * The step between shown stages that loses the most, in words; null when nothing drops.
 * `unscreened` (postings not screened yet) is said only for an all-time pipeline, since
 * it counts every posting.
 */
export function biggestDrop(
  steps: PipelineStep[],
  extras: { needs_you: number; unscreened: number | null },
): { title: string; detail: string } | null {
  let worst = -1;
  let worstRate = 2;
  for (let i = 1; i < steps.length; i++) {
    const before = steps[i - 1].count;
    if (before === 0) continue;
    const rate = steps[i].count / before;
    if (rate < worstRate) {
      worstRate = rate;
      worst = i;
    }
  }
  if (worst < 0 || worstRate >= 1) return null;
  const from = steps[worst - 1];
  const to = steps[worst];
  const lost = from.count - to.count;
  const title = `Biggest drop: ${STAGE_WORDS[from.stage]} to ${STAGE_WORDS[to.stage]}.`;
  const pair = `${from.stage}>${to.stage}`;
  const detail =
    pair === "found>screened_in"
      ? `${lost} found postings weren't screened in${extras.unscreened ? `; ${extras.unscreened} of them haven't been screened yet` : ""}.`
      : pair === "screened_in>tailored"
        ? `${lost} screened-in postings aren't tailored yet.`
        : pair === "tailored>autofilled"
          ? `${lost} tailored postings haven't been autofilled.`
          : pair === "autofilled>sent"
            ? `${lost} filled forms weren't sent${extras.needs_you ? `; ${extras.needs_you} are waiting on you` : ""}.`
            : `${lost} postings ${STAGE_WORDS[from.stage]} weren't ${STAGE_WORDS[to.stage]}.`;
  return { title, detail };
}
