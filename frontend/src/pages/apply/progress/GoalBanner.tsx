import type { ApplyProgress } from "../../../api";
import { Meter, Tile } from "../../../components/ui";
import type { ApplyTab } from "../../../lib/applyPage";
import {
  dayKey,
  goalNudge,
  shortDate,
  waitingLine,
  weekStart,
  type ProgressSummary,
} from "../../../lib/applyProgress";
import { BannerActions } from "./BannerActions";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** This week against the applicant's weekly goal, day by day, and what to do next. */
export function GoalBanner({
  progress,
  summary,
  goal,
  now,
  onTab,
  onSettings,
}: {
  progress: ApplyProgress;
  summary: ProgressSummary;
  goal: number;
  now: Date;
  onTab: (tab: ApplyTab) => void;
  onSettings: () => void;
}) {
  const sent = summary.thisWeek;
  const monday = weekStart(now);
  const sunday = new Date(monday);
  sunday.setDate(sunday.getDate() + 6);
  const todayIndex = (now.getDay() + 6) % 7;
  const waiting = waitingLine(progress);
  return (
    <Tile aria-label="Weekly goal">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-center lg:gap-10">
        <div>
          <p className="rt-eyebrow">
            This week · {shortDate(dayKey(monday))} – {shortDate(dayKey(sunday))}
          </p>
          <p className="mt-2 font-display text-3xl leading-tight text-ink">
            <span className="rt-figure">{sent}</span> of {goal} sent
          </p>
          <Meter
            className="mt-3"
            value={(sent / goal) * 100}
            label="Weekly goal"
            valueText={`${sent} of ${goal} sent`}
          />
          <ol aria-label="Sent each day this week" className="mt-3 grid grid-cols-7 gap-1.5">
            {DAYS.map((day, i) => {
              const count = summary.thisWeekDays[i];
              return (
                <li
                  key={day}
                  aria-current={i === todayIndex ? "date" : undefined}
                  className={`flex flex-col items-center gap-0.5 rounded-sm border py-1.5 ${
                    i === todayIndex ? "border-ink" : "border-line"
                  } ${count > 0 ? "bg-selected-row text-accent" : "bg-paper text-ink-muted"}`}
                >
                  <span className="rt-eyebrow text-[10px]">{day}</span>
                  <span className="text-sm font-medium">{count > 0 ? count : "·"}</span>
                </li>
              );
            })}
          </ol>
        </div>
        <div className="space-y-3">
          <p className="text-[15px] font-medium text-ink">{goalNudge(sent, goal)}</p>
          {waiting && <p className="text-sm text-ink-2">{waiting}</p>}
          <BannerActions progress={progress} onTab={onTab} />
          <p className="text-xs text-ink-muted">
            Goal: {goal} a week ·{" "}
            <button type="button" className="rt-link" onClick={onSettings}>
              Change
            </button>
          </p>
        </div>
      </div>
    </Tile>
  );
}
