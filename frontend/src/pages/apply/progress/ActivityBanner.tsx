import type { ActivityBannerOptions, ApplyProgress } from "../../../api";
import { Tile } from "../../../components/ui";
import type { ApplyTab } from "../../../lib/applyPage";
import {
  daysAgo,
  shortDate,
  summarizeProgress,
  waitingLine,
  type ProgressSummary,
} from "../../../lib/applyProgress";
import {
  ACTIVITY_WEEKS,
  STAGE_ACTIONS,
  STAGE_WORDS,
  customRange,
  heatFill,
  stageTimes,
} from "../../../lib/progressOptions";
import { BannerActions, CustomizeLink } from "./BannerActions";
import { Heatmap } from "./Heatmap";

/** "Last 13 weeks", or a custom range's dates. */
function rangeLabel(options: ActivityBannerOptions, summary: ProgressSummary): string {
  const range = options.range === "custom" ? customRange(options) : null;
  if (range) return `${shortDate(range.from)} – ${shortDate(range.to)}`;
  return `Last ${summary.grid.length} weeks`;
}

/** Postings reaching the chosen stage per day over a range, with the best and last day. */
export function ActivityBanner({
  progress,
  options,
  now,
  onTab,
  onSettings,
}: {
  progress: ApplyProgress;
  options: ActivityBannerOptions;
  now: Date;
  onTab: (tab: ApplyTab) => void;
  onSettings?: () => void;
}) {
  const range = options.range === "custom" ? customRange(options) : null;
  const summary = summarizeProgress(stageTimes(progress, options.counts), now, {
    weeks: options.range === "custom" ? 13 : ACTIVITY_WEEKS[options.range],
    range,
  });
  const word = STAGE_WORDS[options.counts];
  const { bestDay, daysSinceLast } = summary;
  const label = rangeLabel(options, summary);
  const actions = options.show_actions && <BannerActions progress={progress} onTab={onTab} />;

  if (options.compact) {
    const peak = Math.max(1, ...summary.weekly);
    return (
      <Tile aria-label="Your activity">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <p className="text-sm text-ink">
            <span className="rt-eyebrow mr-2">{label}</span>
            <span className="rt-figure font-display text-xl">{summary.inRange}</span> {word}
          </p>
          <div
            role="img"
            aria-label={`${word} per week: ${summary.weekly.join(", ")}`}
            className="flex h-7 items-end gap-0.5"
          >
            {summary.weekly.map((count, i) => (
              <span
                key={i}
                className="w-1.5 rounded-[1px] bg-sunken"
                style={{
                  height: `${Math.max(12, (count / peak) * 100)}%`,
                  background: count ? heatFill(4) : undefined,
                }}
              />
            ))}
          </div>
          {options.show_stats && bestDay && (
            <p className="text-sm text-ink-2">
              Best day {shortDate(bestDay.key)} · {bestDay.count} {word}
            </p>
          )}
          <div className="ml-auto">{actions}</div>
        </div>
      </Tile>
    );
  }

  const waiting = options.show_waiting && waitingLine(progress);
  return (
    <Tile aria-label="Your activity">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-12">
        <div className="min-w-0 flex-1 space-y-2.5 lg:min-w-64">
          <p className="rt-eyebrow">{label}</p>
          <p className="font-display text-3xl leading-tight text-ink">
            <span className="rt-figure">{summary.inRange}</span> {word}
          </p>
          {options.show_stats && (
            <>
              {bestDay && (
                <p className="text-sm text-ink-2">
                  Best day <span className="font-medium text-ink">{shortDate(bestDay.key)}</span> ·{" "}
                  {bestDay.count} {word}
                </p>
              )}
              <p className="text-sm text-ink-2">
                {daysSinceLast === null
                  ? `Nothing ${word} yet. Your first one starts the chart.`
                  : daysSinceLast === 0
                    ? `Some ${word} today. Keep it going.`
                    : `Last ${word} ${daysAgo(daysSinceLast)}. ${STAGE_ACTIONS[options.counts]} today to start a new run.`}
              </p>
            </>
          )}
          {waiting && <p className="text-sm text-ink-2">{waiting}</p>}
        </div>
        <Heatmap
          summary={summary}
          label={`${summary.inRange} ${word}, ${label.toLowerCase()}${bestDay ? `, most on ${shortDate(bestDay.key)}` : ""}`}
          word={word}
        />
      </div>
      {(actions || onSettings) && (
        <div className="mt-5 flex flex-wrap items-center gap-4">
          {actions}
          {onSettings && <CustomizeLink onSettings={onSettings} />}
        </div>
      )}
    </Tile>
  );
}
