/**
 * The Apply progress banner's numbers, worked out in the applicant's own time zone from
 * the stage times `/api/applications/progress` returns. Weeks start on Monday unless the
 * goal banner is set to Sunday. The pipeline's own math is in `lib/applyPipeline.ts`.
 */

/** One posting's time at the stage a banner counts. */
export type TimedItem = { at: string; company?: string };

export type DayCell = {
  key: string;
  count: number;
  future: boolean;
  today: boolean;
  /** Before or after a custom range, inside the range's first or last week. */
  outside: boolean;
};

/** 1: weeks start on Monday; 0: on Sunday. */
export type WeekStartDay = 0 | 1;

export type ProgressSummary = {
  /** Counted in the current week, and per day from its first day. */
  thisWeek: number;
  thisWeekDays: number[];
  /** Per week, oldest first, over the grid's weeks. */
  weekly: number[];
  /** `weekly` as a week-by-day grid (columns oldest first, the week's first day on top). */
  grid: DayCell[][];
  /** Within the grid's weeks (and a custom range's days). */
  inRange: number;
  bestDay: { key: string; count: number } | null;
  /** Whole days since the last one; null when there never was one. */
  daysSinceLast: number | null;
  total: number;
};

export type SummaryOptions = {
  /** How many weeks the grid covers, ending with the current one. */
  weeks?: number;
  weekStartsOn?: WeekStartDay;
  /** A custom range (`YYYY-MM-DD`, both ends included) instead of `weeks`. */
  range?: { from: string; to: string } | null;
};

/** The most weeks a custom range draws; a longer one shows its last weeks. */
export const MAX_WEEKS = 104;

const DAY_MS = 86_400_000;

/** `YYYY-MM-DD` of `date` in local time. */
export function dayKey(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Local midnight of `YYYY-MM-DD`. */
export function parseDayKey(key: string): Date {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Local midnight of the week's first day (Monday, or Sunday) on or before `date`. */
export function weekStart(date: Date, startsOn: WeekStartDay = 1): Date {
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  start.setDate(start.getDate() - ((start.getDay() - startsOn + 7) % 7));
  return start;
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

/** Day counts per local day, and the latest time. */
function perDayCounts(items: TimedItem[]): { perDay: Map<string, number>; last: Date | null } {
  const perDay = new Map<string, number>();
  let last: Date | null = null;
  for (const item of items) {
    const at = new Date(item.at);
    if (Number.isNaN(at.getTime())) continue;
    const key = dayKey(at);
    perDay.set(key, (perDay.get(key) ?? 0) + 1);
    if (!last || at > last) last = at;
  }
  return { perDay, last };
}

/** The grid's first week and how many weeks it has. */
function gridWeeks(now: Date, options: SummaryOptions): { first: Date; weeks: number } {
  const startsOn = options.weekStartsOn ?? 1;
  if (options.range) {
    const first = weekStart(parseDayKey(options.range.from), startsOn);
    const last = weekStart(parseDayKey(options.range.to), startsOn);
    const weeks = Math.round((last.getTime() - first.getTime()) / (7 * DAY_MS)) + 1;
    if (weeks <= MAX_WEEKS) return { first, weeks };
    return { first: addDays(last, -7 * (MAX_WEEKS - 1)), weeks: MAX_WEEKS };
  }
  const weeks = Math.max(1, options.weeks ?? 13);
  return { first: addDays(weekStart(now, startsOn), -7 * (weeks - 1)), weeks };
}

export function summarizeProgress(
  items: TimedItem[],
  now: Date,
  options: SummaryOptions = {},
): ProgressSummary {
  const { perDay, last } = perDayCounts(items);
  const startsOn = options.weekStartsOn ?? 1;
  const today = dayKey(now);
  const { first, weeks } = gridWeeks(now, options);
  const from = options.range?.from;
  const to = options.range?.to;
  const grid: DayCell[][] = [];
  for (let w = 0; w < weeks; w++) {
    const column: DayCell[] = [];
    for (let d = 0; d < 7; d++) {
      const key = dayKey(addDays(first, w * 7 + d));
      const outside = (!!from && key < from) || (!!to && key > to);
      column.push({
        key,
        count: outside ? 0 : (perDay.get(key) ?? 0),
        future: key > today,
        today: key === today,
        outside,
      });
    }
    grid.push(column);
  }
  const weekly = grid.map((column) => column.reduce((sum, cell) => sum + cell.count, 0));
  const current = weekStart(now, startsOn);
  const thisWeekDays = Array.from(
    { length: 7 },
    (_, d) => perDay.get(dayKey(addDays(current, d))) ?? 0,
  );

  let bestDay: ProgressSummary["bestDay"] = null;
  for (const cell of grid.flat())
    if (cell.count > 0 && (!bestDay || cell.count > bestDay.count))
      bestDay = { key: cell.key, count: cell.count };

  const lastDay = last ? new Date(last.getFullYear(), last.getMonth(), last.getDate()) : null;
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return {
    thisWeek: thisWeekDays.reduce((sum, n) => sum + n, 0),
    thisWeekDays,
    weekly,
    grid,
    inRange: weekly.reduce((sum, n) => sum + n, 0),
    bestDay,
    daysSinceLast: lastDay ? Math.round((todayStart.getTime() - lastDay.getTime()) / DAY_MS) : null,
    total: items.length,
  };
}

/** Heatmap shade 0–4 for a day's count. */
export function heatLevel(count: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0) return 0;
  if (count < 3) return 1;
  if (count < 6) return 2;
  if (count < 12) return 3;
  return 4;
}

/** The weekly-goal banner's one-line nudge; `verb` is what counts ("Send", "Tailor"). */
export function goalNudge(done: number, goal: number, verb = "Send"): string {
  if (done >= goal) return "Goal reached. Anything more this week is a bonus.";
  const half = Math.ceil(goal / 2);
  if (done === 0) return `A fresh week. ${verb} ${half} and you’re halfway there.`;
  if (done < half) return `${goal - done} to go. ${half - done} more and you’re halfway.`;
  return `Past halfway. ${goal - done} to go.`;
}

/** "today", "yesterday", "25 days ago". */
export function daysAgo(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `2026-09-24` → "Sep 24". */
export function shortDate(key: string): string {
  const [, m, d] = key.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}`;
}

/** Day names in week order, starting Monday or Sunday. */
export function weekdayNames(startsOn: WeekStartDay): string[] {
  const monday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return startsOn === 1 ? monday : ["Sun", ...monday.slice(0, 6)];
}

/**
 * The month over each heatmap column: shown where a month starts, unless the label
 * before it is under three columns away (it would run into it). A first column whose
 * month ends within two weeks stays blank for the same reason.
 */
export function monthLabels(grid: DayCell[][]): string[] {
  const months = grid.map((column) => Number(column[0].key.slice(5, 7)) - 1);
  const labels: string[] = [];
  let last = -3;
  months.forEach((month, w) => {
    const starts = w === 0 ? months[1] === month && months[2] === month : month !== months[w - 1];
    const show = starts && w - last >= 3;
    if (show) last = w;
    labels.push(show ? MONTHS[month] : "");
  });
  return labels;
}

/** "2 are ready to fill and 21 are waiting on you." — or null when neither. */
export function waitingLine(counts: { ready: number; needs_you: number }): string | null {
  const are = (n: number) => (n === 1 ? "is" : "are");
  const parts = [
    counts.ready > 0 && `${counts.ready} ${are(counts.ready)} ready to fill`,
    counts.needs_you > 0 && `${counts.needs_you} ${are(counts.needs_you)} waiting on you`,
  ].filter(Boolean);
  return parts.length ? `${parts.join(" and ")}.` : null;
}
