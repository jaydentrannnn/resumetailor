import { describe, expect, it } from "vitest";
import {
  biggestDrop,
  daysAgo,
  dayKey,
  goalNudge,
  heatLevel,
  monthLabels,
  pipelineSteps,
  shortDate,
  summarizeProgress,
  weekStart,
} from "./applyProgress";

/** A send at local time, as the API would return it (UTC ISO). */
const at = (y: number, m: number, d: number, h = 12) => ({
  at: new Date(y, m - 1, d, h).toISOString(),
  company: "Acme",
});

describe("applyProgress", () => {
  const now = new Date(2026, 9, 21, 15); // Wednesday, Oct 21

  it("starts weeks on Monday in local time", () => {
    expect(dayKey(weekStart(now))).toBe("2026-10-19");
    expect(dayKey(weekStart(new Date(2026, 9, 25)))).toBe("2026-10-19"); // Sunday
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
    expect(summary.bestWeek).toEqual({ start: "2026-10-19", count: 3 });
    expect(summary.daysSinceLast).toBe(0);
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

  it("has nothing to report before the first send", () => {
    const summary = summarizeProgress([], now);
    expect([summary.total, summary.daysSinceLast, summary.bestDay, summary.bestWeek]).toEqual([
      0,
      null,
      null,
      null,
    ]);
  });

  it("counts companies once, whatever their case", () => {
    const sent = [at(2026, 10, 1), { ...at(2026, 10, 2), company: " acme " }];
    expect(summarizeProgress(sent, now).companies).toBe(1);
  });

  it("words the goal, the gap and the dates", () => {
    expect(goalNudge(0, 10)).toBe("A fresh week. Send 5 and you’re halfway there.");
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
  const counts = {
    found: 198,
    screened_in: 54,
    tailored: 52,
    autofilled: 50,
    sent_total: 28,
    needs_you: 21,
    unscreened: 104,
  };

  it("shows each stage as a share of what was found and of the stage before", () => {
    const steps = pipelineSteps(counts);
    expect(steps.map((step) => step.share)).toEqual([100, 27, 26, 25, 14]);
    expect(steps[4].rate).toBe("56% of autofilled");
  });

  it("names the stage that loses the most", () => {
    expect(biggestDrop(counts)).toEqual({
      title: "Biggest drop: found to screened in.",
      detail: "144 found postings weren't screened in; 104 of them haven't been screened yet.",
    });
    expect(
      biggestDrop({
        ...counts,
        found: 0,
        screened_in: 0,
        tailored: 0,
        autofilled: 0,
        sent_total: 0,
      }),
    ).toBeNull();
  });
});

describe("monthLabels", () => {
  const column = (key: string) => [{ key, count: 0, future: false, today: false }];

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
