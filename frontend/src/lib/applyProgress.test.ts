import { describe, expect, it } from "vitest";
import type { ApplyProgress, PostingTimes } from "../api";
import {
  biggestDrop,
  pipelineHeadline,
  pipelineSteps,
  pipelineWindow,
  stageCounts,
} from "./applyPipeline";
import {
  daysAgo,
  dayKey,
  goalNudge,
  heatLevel,
  monthLabels,
  shortDate,
  summarizeProgress,
  weekStart,
  weekdayNames,
} from "./applyProgress";
import { STAGE_ORDER, pipelineOptions, stageTimes } from "./progressOptions";

/** A time at local `y-m-d h:00`, as the API would return it (UTC ISO). */
const iso = (y: number, m: number, d: number, h = 12) => new Date(y, m - 1, d, h).toISOString();
const at = (y: number, m: number, d: number, h = 12) => ({ at: iso(y, m, d, h), company: "Acme" });

describe("applyProgress", () => {
  const now = new Date(2026, 9, 21, 15); // Wednesday, Oct 21

  it("starts weeks on Monday, or Sunday, in local time", () => {
    expect(dayKey(weekStart(now))).toBe("2026-10-19");
    expect(dayKey(weekStart(new Date(2026, 9, 25)))).toBe("2026-10-19"); // Sunday
    expect(dayKey(weekStart(now, 0))).toBe("2026-10-18");
    expect(dayKey(weekStart(new Date(2026, 9, 25), 0))).toBe("2026-10-25");
    expect(weekdayNames(0)[0]).toBe("Sun");
  });

  it("counts this week by day and every week back from it", () => {
    const sent = [at(2026, 10, 19), at(2026, 10, 19, 23), at(2026, 10, 21), at(2026, 9, 24)];
    const summary = summarizeProgress(sent, now);
    expect(summary.thisWeek).toBe(3);
    expect(summary.thisWeekDays).toEqual([2, 0, 1, 0, 0, 0, 0]);
    expect(summary.weekly).toHaveLength(13);
    expect(summary.weekly.at(-5)).toBe(1); // the week of Sep 21
    expect(summary.inRange).toBe(4);
    expect(summary.bestDay).toEqual({ key: "2026-10-19", count: 2 });
    expect(summary.daysSinceLast).toBe(0);
    // A Sunday-first week moves Sunday Oct 18 in and counts from it.
    const sunday = summarizeProgress([...sent, at(2026, 10, 18)], now, { weekStartsOn: 0 });
    expect(sunday.thisWeekDays).toEqual([1, 2, 0, 1, 0, 0, 0]);
    expect(summarizeProgress(sent, now, { weeks: 4 }).grid).toHaveLength(4);
  });

  it("draws a custom range by whole weeks, blanking the days outside it", () => {
    const sent = [at(2026, 9, 1), at(2026, 9, 2), at(2026, 9, 30)];
    const summary = summarizeProgress(sent, now, {
      range: { from: "2026-09-02", to: "2026-09-29" },
    });
    expect(summary.grid[0][0].key).toBe("2026-08-31"); // the Monday before Sep 2
    expect(summary.grid.at(-1)![6].key).toBe("2026-10-04");
    expect(summary.inRange).toBe(1); // Sep 1 and Sep 30 sit outside
    expect(summary.grid[0][1]).toMatchObject({ key: "2026-09-01", outside: true, count: 0 });
  });

  it("marks today and the days still to come in the grid", () => {
    const column = summarizeProgress([], now).grid.at(-1)!;
    expect(column.map((cell) => [cell.today, cell.future])).toEqual([
      [false, false],
      [false, false],
      [true, false],
      [false, true],
      [false, true],
      [false, true],
      [false, true],
    ]);
  });

  it("has nothing to report before the first one", () => {
    const summary = summarizeProgress([], now);
    expect([summary.total, summary.daysSinceLast, summary.bestDay]).toEqual([0, null, null]);
  });

  it("words the goal, the gap and the dates", () => {
    expect(goalNudge(0, 10)).toBe("A fresh week. Send 5 and you’re halfway there.");
    expect(goalNudge(0, 10, "Tailor")).toBe("A fresh week. Tailor 5 and you’re halfway there.");
    expect(goalNudge(2, 10)).toBe("8 to go. 3 more and you’re halfway.");
    expect(goalNudge(6, 10)).toBe("Past halfway. 4 to go.");
    expect(goalNudge(10, 10)).toMatch(/^Goal reached/);
    expect([heatLevel(0), heatLevel(2), heatLevel(5), heatLevel(11), heatLevel(22)]).toEqual([
      0, 1, 2, 3, 4,
    ]);
    expect([daysAgo(0), daysAgo(1), daysAgo(25)]).toEqual(["today", "yesterday", "25 days ago"]);
    expect(shortDate("2026-09-24")).toBe("Sep 24");
  });
});

describe("pipeline", () => {
  const counts = { found: 198, screened_in: 54, tailored: 52, autofilled: 50, sent: 28 };
  const extras = { needs_you: 21, unscreened: 104 };

  it("shows each stage as a share of the first and of the stage before", () => {
    const steps = pipelineSteps(counts, STAGE_ORDER);
    expect(steps.map((step) => step.share)).toEqual([100, 27, 26, 25, 14]);
    expect(steps[4].rate).toBe("56% of autofilled");
    expect(pipelineHeadline(steps)).toBe("14% of the postings found were sent.");
    const two = pipelineSteps(counts, ["tailored", "sent"]);
    expect(two.map((step) => [step.share, step.rate])).toEqual([
      [100, "of the postings tailored"],
      [54, "54% of tailored"],
    ]);
    expect(pipelineHeadline(two)).toBe("54% of the postings tailored were sent.");
  });

  it("names the stage that loses the most", () => {
    expect(biggestDrop(pipelineSteps(counts, STAGE_ORDER), extras)).toEqual({
      title: "Biggest drop: found to screened in.",
      detail: "144 found postings weren't screened in; 104 of them haven't been screened yet.",
    });
    expect(biggestDrop(pipelineSteps(counts, ["found", "sent"]), extras)?.detail).toBe(
      "170 postings found weren't sent.",
    );
    const none = { found: 0, screened_in: 0, tailored: 0, autofilled: 0, sent: 0 };
    expect(biggestDrop(pipelineSteps(none, STAGE_ORDER), extras)).toBeNull();
  });

  it("counts only the postings found in the chosen dates", () => {
    const posting = (found: string | null, sent: string | null): PostingTimes => ({
      company: "Acme",
      found_at: found,
      screened_in_at: sent,
      tailored_at: sent,
      autofilled_at: sent,
      sent_at: sent,
    });
    const progress = {
      postings: [
        posting(iso(2026, 10, 20), iso(2026, 10, 21)),
        posting(iso(2026, 10, 2), null),
        posting(iso(2026, 8, 1), iso(2026, 8, 3)),
      ],
    } as ApplyProgress;
    const now = new Date(2026, 9, 21, 15);
    expect(stageCounts(progress, { from: null, to: null })).toMatchObject({ found: 3, sent: 2 });
    const week = pipelineWindow({ range: "week", start: null, end: null }, now);
    expect(week.label).toBe("this week");
    expect(stageCounts(progress, week)).toMatchObject({ found: 1, sent: 1 });
    const month = pipelineWindow({ range: "month", start: null, end: null }, now);
    expect(stageCounts(progress, month)).toMatchObject({ found: 2, sent: 1 });
    const custom = pipelineWindow({ range: "custom", start: "2026-10-31", end: "2026-07-01" }, now);
    expect(custom.label).toBe("Jul 1 – Oct 31");
    expect(stageCounts(progress, custom).found).toBe(3);
    expect(pipelineWindow({ range: "custom", start: null, end: null }, now).label).toBe("all time");
    expect(stageTimes(progress, "sent")).toHaveLength(2);
  });

  it("keeps the saved stages in funnel order and never fewer than two", () => {
    expect(pipelineOptions({ pipeline_banner: { stages: ["sent", "found"] } }).stages).toEqual([
      "found",
      "sent",
    ]);
    expect(pipelineOptions({ pipeline_banner: { stages: ["sent"] } }).stages).toEqual(STAGE_ORDER);
  });
});

describe("monthLabels", () => {
  const column = (key: string) => [{ key, count: 0, future: false, today: false, outside: false }];

  it("labels where a month starts, never two within three columns", () => {
    const grid = [
      "2026-07-27",
      "2026-08-03",
      "2026-08-10",
      "2026-08-17",
      "2026-08-31",
      "2026-09-07",
    ];
    expect(monthLabels(grid.map(column))).toEqual(["", "Aug", "", "", "", "Sep"]);
    const tight = ["2026-07-20", "2026-07-27", "2026-08-03", "2026-08-10", "2026-08-17"];
    expect(monthLabels(tight.map(column))).toEqual(["", "", "Aug", "", ""]);
  });
});
