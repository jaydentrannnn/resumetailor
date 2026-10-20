import type { ActivityBannerOptions } from "../../../api";
import {
  heatLevel,
  monthLabels,
  shortDate,
  type ProgressSummary,
} from "../../../lib/applyProgress";
import { heatFill } from "../../../lib/progressOptions";

const WEEKDAY_LABELS = ["Mon", "", "Wed", "", "Fri", "", "Sun"];
const LEVELS = [0, 1, 2, 3, 4];

/** The activity banner's day-by-week grid, in the chosen color, with its legend. */
export function Heatmap({
  summary,
  color,
  label,
  word,
}: {
  summary: ProgressSummary;
  color: ActivityBannerOptions["color"];
  /** What the whole grid says, for screen readers. */
  label: string;
  /** What a day counts ("sent"), for each cell's tooltip. */
  word: string;
}) {
  const months = monthLabels(summary.grid);
  const fill = (level: number) => (level ? { background: heatFill(color, level) } : undefined);
  return (
    <div className="max-w-full overflow-x-auto">
      <div role="img" aria-label={label} className="flex gap-1">
        <div aria-hidden className="mr-1 flex flex-col gap-1 pt-[18px]">
          {WEEKDAY_LABELS.map((day, i) => (
            <span key={i} className="h-3.5 font-mono text-[10px] leading-[14px] text-ink-muted">
              {day}
            </span>
          ))}
        </div>
        {summary.grid.map((column, w) => (
          <div key={column[0].key} aria-hidden className="flex flex-col gap-1">
            <span className="h-3.5 w-3.5 overflow-visible whitespace-nowrap font-mono text-[10px] text-ink-muted">
              {months[w]}
            </span>
            {column.map((cell) => {
              const level = heatLevel(cell.count);
              const blank = cell.future || cell.outside;
              return (
                <span
                  key={cell.key}
                  title={`${shortDate(cell.key)}: ${cell.count} ${word}`}
                  className={`size-3.5 rounded-[3px] ${blank ? "border border-line" : "bg-sunken"} ${
                    cell.today ? "outline outline-1 outline-ink" : ""
                  }`}
                  style={blank ? undefined : fill(level)}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div
        aria-hidden
        className="mt-2 flex items-center justify-end gap-1 text-[11px] text-ink-muted"
      >
        Less
        {LEVELS.map((level) => (
          <span key={level} className="size-3.5 rounded-[3px] bg-sunken" style={fill(level)} />
        ))}
        More
      </div>
    </div>
  );
}
