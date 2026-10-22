import {
  heatLevel,
  monthLabels,
  shortDate,
  type ProgressSummary,
} from "../../../lib/applyProgress";
import { heatFill, heatmapAxes } from "../../../lib/progressOptions";

const WEEKDAY_LABELS = ["Mon", "", "Wed", "", "Fri", "", "Sun"];
/** Largest cell edge in px; below it, cells scale with the banner's width. */
const MAX_CELL = 28;
/** Gap between cells (`gap-1`) in px. */
const GAP = 4;
/** Room for the weekday labels beside the grid, or the month labels in the transposed one. */
const LABELS = { normal: 28, transposed: 32 };
/** Takes up to 3/5 of a wide banner, pinned top-right (right-aligned when the banner stacks). */
const ROOT = "w-full min-w-0 self-end lg:w-3/5 lg:self-start";

/**
 * The widest the grid may get before its cells would pass MAX_CELL. As a `maxWidth`,
 * it keeps short ranges compact and packed instead of growing tall to fill the width.
 */
function maxWidth(columns: number, labels: number): string {
  return `${columns * MAX_CELL + (columns - 1) * GAP + labels}px`;
}

/** The activity banner's day-by-week grid, in the accent color. */
export function Heatmap({
  summary,
  label,
  word,
}: {
  summary: ProgressSummary;
  /** What the whole grid says, for screen readers. */
  label: string;
  /** What a day counts ("sent"), for each cell's tooltip. */
  word: string;
}) {
  const months = monthLabels(summary.grid);
  const { transpose } = heatmapAxes(summary.grid.length);
  const fill = (level: number) => (level ? { background: heatFill(level) } : undefined);
  const cellClass = (blank: boolean, today: boolean) =>
    `aspect-square w-full rounded-[3px] ${blank ? "border border-line" : "bg-sunken"} ${
      today ? "outline outline-1 outline-ink" : ""
    }`;
  const tracks = (count: number) => `repeat(${count}, minmax(0, 1fr))`;

  if (transpose) {
    // Weekdays across, weeks down: long edge horizontal when few weeks.
    return (
      <div className={ROOT} style={{ maxWidth: maxWidth(7, LABELS.transposed) }}>
        <div role="img" aria-label={label} className="flex flex-col gap-1">
          <div
            aria-hidden
            className="grid gap-1 pl-8"
            style={{ gridTemplateColumns: tracks(7) }}
          >
            {WEEKDAY_LABELS.map((day, i) => (
              <span key={i} className="text-center font-mono text-[10px] text-ink-muted">
                {day}
              </span>
            ))}
          </div>
          {summary.grid.map((column, w) => (
            <div key={column[0].key} className="flex items-center gap-1">
              <span className="w-7 shrink-0 font-mono text-[10px] text-ink-muted">
                {months[w]}
              </span>
              <div className="grid min-w-0 flex-1 gap-1" style={{ gridTemplateColumns: tracks(7) }}>
                {column.map((cell) => {
                  const level = heatLevel(cell.count);
                  const blank = cell.future || cell.outside;
                  return (
                    <span
                      key={cell.key}
                      title={`${shortDate(cell.key)}: ${cell.count} ${word}`}
                      className={cellClass(blank, cell.today)}
                      style={blank ? undefined : fill(level)}
                    />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={ROOT} style={{ maxWidth: maxWidth(summary.grid.length, LABELS.normal) }}>
      <div role="img" aria-label={label} className="flex gap-1">
        <div aria-hidden className="mr-1 flex flex-col gap-1 pt-[14px]">
          {WEEKDAY_LABELS.map((day, i) => (
            <span
              key={i}
              className="flex flex-1 items-center font-mono text-[10px] leading-none text-ink-muted"
            >
              {day}
            </span>
          ))}
        </div>
        <div
          className="grid min-w-0 flex-1 gap-1"
          style={{ gridTemplateColumns: tracks(summary.grid.length) }}
        >
          {summary.grid.map((column, w) => (
            <div key={column[0].key} className="flex min-w-0 flex-col gap-1">
              <span className="h-3.5 overflow-visible whitespace-nowrap font-mono text-[10px] text-ink-muted">
                {months[w]}
              </span>
              {column.map((cell) => {
                const level = heatLevel(cell.count);
                const blank = cell.future || cell.outside;
                return (
                  <span
                    key={cell.key}
                    title={`${shortDate(cell.key)}: ${cell.count} ${word}`}
                    className={cellClass(blank, cell.today)}
                    style={blank ? undefined : fill(level)}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
