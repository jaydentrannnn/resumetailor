import type { ApplyProgress } from "../../../api";
import { Tile } from "../../../components/ui";
import type { ApplyTab } from "../../../lib/applyPage";
import {
  daysAgo,
  heatLevel,
  monthLabels,
  shortDate,
  waitingLine,
  type ProgressSummary,
} from "../../../lib/applyProgress";
import { BannerActions } from "./BannerActions";

const SHADE = ["bg-sunken", "bg-accent/20", "bg-accent/40", "bg-accent/70", "bg-accent"];
const WEEKDAY_LABELS = ["Mon", "", "Wed", "", "Fri", "", "Sun"];

/** Sends per day over the last 13 weeks, with the best day and the last send. */
export function ActivityBanner({
  progress,
  summary,
  onTab,
}: {
  progress: ApplyProgress;
  summary: ProgressSummary;
  onTab: (tab: ApplyTab) => void;
}) {
  const { grid, bestDay, daysSinceLast } = summary;
  const waiting = waitingLine(progress);
  const weeks = grid.length;
  const months = monthLabels(grid);
  return (
    <Tile aria-label="Your activity">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-12">
        <div className="min-w-0 flex-1 space-y-2.5">
          <p className="rt-eyebrow">Last {weeks} weeks</p>
          <p className="font-display text-3xl leading-tight text-ink">
            <span className="rt-figure">{summary.inRange}</span> sent
          </p>
          {bestDay && (
            <p className="text-sm text-ink-2">
              Best day <span className="font-medium text-ink">{shortDate(bestDay.key)}</span> ·{" "}
              {bestDay.count} sent
            </p>
          )}
          <p className="text-sm text-ink-2">
            {daysSinceLast === null
              ? "Nothing sent yet. Your first one starts the chart."
              : daysSinceLast === 0
                ? "Sent today. Keep it going."
                : `Last sent ${daysAgo(daysSinceLast)}. Send one today to start a new run.`}
          </p>
          {waiting && <p className="text-sm text-ink-2">{waiting}</p>}
          <div className="pt-1">
            <BannerActions progress={progress} onTab={onTab} />
          </div>
        </div>
        <div className="overflow-x-auto">
          <div
            role="img"
            aria-label={`${summary.inRange} sent in the last ${weeks} weeks${bestDay ? `, most on ${shortDate(bestDay.key)}` : ""}`}
            className="flex gap-1"
          >
            <div aria-hidden className="mr-1 flex flex-col gap-1 pt-[18px]">
              {WEEKDAY_LABELS.map((label, i) => (
                <span key={i} className="h-3.5 font-mono text-[10px] leading-[14px] text-ink-muted">
                  {label}
                </span>
              ))}
            </div>
            {grid.map((column, w) => (
              <div key={column[0].key} aria-hidden className="flex flex-col gap-1">
                <span className="h-3.5 w-3.5 overflow-visible whitespace-nowrap font-mono text-[10px] text-ink-muted">
                  {months[w]}
                </span>
                {column.map((cell) => (
                  <span
                    key={cell.key}
                    title={`${shortDate(cell.key)}: ${cell.count} sent`}
                    className={`size-3.5 rounded-[3px] ${
                      cell.future ? "border border-line" : SHADE[heatLevel(cell.count)]
                    } ${cell.today ? "outline outline-1 outline-ink" : ""}`}
                  />
                ))}
              </div>
            ))}
          </div>
          <div
            aria-hidden
            className="mt-2 flex items-center justify-end gap-1 text-[11px] text-ink-muted"
          >
            Less
            {SHADE.map((shade) => (
              <span key={shade} className={`size-3.5 rounded-[3px] ${shade}`} />
            ))}
            More
          </div>
        </div>
      </div>
    </Tile>
  );
}
