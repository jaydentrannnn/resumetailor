/**
 * The Apply progress banner's numbers, worked out in the applicant's own time zone from
 * the send times `/api/applications/progress` returns. Weeks start on Monday.
 */

export type SentApplication = { at: string; company: string };

export type DayCell = { key: string; count: number; future: boolean; today: boolean };

export type ProgressSummary = {
  /** Sent in the current week, and per day Monday…Sunday. */
  thisWeek: number;
  thisWeekDays: number[];
  /** Sent per week, oldest first; the last entry is the current week. */
  weekly: number[];
  /** `weekly` as a week-by-day grid (columns oldest first, Monday at the top). */
  grid: DayCell[][];
  /** Within the grid's weeks. */
  inRange: number;
  bestDay: { key: string; count: number } | null;
  bestWeek: { start: string; count: number } | null;
  /** Whole days since the last send; null when nothing was ever sent. */
  daysSinceLast: number | null;
  companies: number;
  total: number;
};

const DAY_MS = 86_400_000;

/** `YYYY-MM-DD` of `date` in local time. */
export function dayKey(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Local midnight of the Monday on or before `date`. */
export function weekStart(date: Date): Date {
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  return start;
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function summarizeProgress(sent: SentApplication[], now: Date, weeks = 13): ProgressSummary {
  const perDay = new Map<string, number>();
  let last: Date | null = null;
  for (const item of sent) {
    const at = new Date(item.at);
    if (Number.isNaN(at.getTime())) continue;
    const key = dayKey(at);
    perDay.set(key, (perDay.get(key) ?? 0) + 1);
    if (!last || at > last) last = at;
  }

  const today = dayKey(now);
  const current = weekStart(now);
  const first = addDays(current, -7 * (weeks - 1));
  const grid: DayCell[][] = [];
  for (let w = 0; w < weeks; w++) {
    const column: DayCell[] = [];
    for (let d = 0; d < 7; d++) {
      const key = dayKey(addDays(first, w * 7 + d));
      column.push({ key, count: perDay.get(key) ?? 0, future: key > today, today: key === today });
    }
    grid.push(column);
  }
  const weekly = grid.map((column) => column.reduce((sum, cell) => sum + cell.count, 0));
  const thisWeekDays = grid[grid.length - 1].map((cell) => cell.count);

  let bestDay: ProgressSummary["bestDay"] = null;
  for (const [key, count] of perDay)
    if (!bestDay || count > bestDay.count) bestDay = { key, count };
  const perWeek = new Map<string, number>();
  for (const [key, count] of perDay) {
    const [y, m, d] = key.split("-").map(Number);
    const start = dayKey(weekStart(new Date(y, m - 1, d)));
    perWeek.set(start, (perWeek.get(start) ?? 0) + count);
  }
  let bestWeek: ProgressSummary["bestWeek"] = null;
  for (const [start, count] of perWeek)
    if (!bestWeek || count > bestWeek.count) bestWeek = { start, count };

  const lastDay = last ? new Date(last.getFullYear(), last.getMonth(), last.getDate()) : null;
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return {
    thisWeek: thisWeekDays.reduce((sum, n) => sum + n, 0),
    thisWeekDays,
    weekly,
    grid,
    inRange: weekly.reduce((sum, n) => sum + n, 0),
    bestDay,
    bestWeek,
    daysSinceLast: lastDay ? Math.round((todayStart.getTime() - lastDay.getTime()) / DAY_MS) : null,
    companies: new Set(sent.map((item) => item.company.trim().toLowerCase())).size,
    total: sent.length,
  };
}

/** Heatmap shade 0–4 for a day's sends. */
export function heatLevel(count: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0) return 0;
  if (count < 3) return 1;
  if (count < 6) return 2;
  if (count < 12) return 3;
  return 4;
}

/** The weekly-goal banner's one-line nudge. */
export function goalNudge(sent: number, goal: number): string {
  if (sent >= goal) return "Goal reached. Anything more this week is a bonus.";
  const half = Math.ceil(goal / 2);
  if (sent === 0) return `A fresh week. Send ${half} and you’re halfway there.`;
  if (sent < half) return `${goal - sent} to go. ${half - sent} more and you’re halfway.`;
  return `Past halfway. ${goal - sent} to go.`;
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

export type PipelineCounts = {
  found: number;
  screened_in: number;
  tailored: number;
  autofilled: number;
  sent_total: number;
  needs_you: number;
  unscreened: number;
};

export type PipelineStep = { label: string; count: number; share: number; rate: string };

/** Found → Screened in → Tailored → Autofilled → Sent, each as a share of Found. */
export function pipelineSteps(counts: PipelineCounts): PipelineStep[] {
  const raw: [string, number][] = [
    ["Found", counts.found],
    ["Screened in", counts.screened_in],
    ["Tailored", counts.tailored],
    ["Autofilled", counts.autofilled],
    ["Sent", counts.sent_total],
  ];
  const pct = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 100) : 0);
  return raw.map(([label, count], i) => ({
    label,
    count,
    share: pct(count, counts.found),
    rate:
      i === 0
        ? "every posting your sources found"
        : `${pct(count, raw[i - 1][1])}% of ${raw[i - 1][0].toLowerCase()}`,
  }));
}

/** The step that loses the most postings, in words; null before anything was found. */
export function biggestDrop(counts: PipelineCounts): { title: string; detail: string } | null {
  const steps = pipelineSteps(counts);
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
  const lost = steps[worst - 1].count - steps[worst].count;
  const title = `Biggest drop: ${steps[worst - 1].label.toLowerCase()} to ${steps[worst].label.toLowerCase()}.`;
  const details: Record<number, string> = {
    1: `${lost} found postings weren't screened in${counts.unscreened ? `; ${counts.unscreened} of them haven't been screened yet` : ""}.`,
    2: `${lost} screened-in postings aren't tailored yet.`,
    3: `${lost} tailored postings haven't been autofilled.`,
    4: `${lost} filled forms weren't sent${counts.needs_you ? `; ${counts.needs_you} are waiting on you` : ""}.`,
  };
  return { title, detail: details[worst] };
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
