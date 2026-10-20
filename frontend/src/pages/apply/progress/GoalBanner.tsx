import type { ApplyProgress, GoalBannerOptions } from "../../../api";
import { Meter, Tile } from "../../../components/ui";
import type { ApplyTab } from "../../../lib/applyPage";
import {
  addDays,
  dayKey,
  goalNudge,
  shortDate,
  summarizeProgress,
  waitingLine,
  weekStart,
  weekdayNames,
} from "../../../lib/applyProgress";
import { STAGE_WORDS, stageTimes } from "../../../lib/progressOptions";
import { BannerActions } from "./BannerActions";

const NUDGE_VERB: Record<GoalBannerOptions["counts"], string> = {
  sent: "Send",
  autofilled: "Autofill",
  tailored: "Tailor",
};

/** This week against the applicant's weekly goal, day by day, and what to do next. */
export function GoalBanner({
  progress,
  options,
  goal,
  now,
  onTab,
  onSettings,
}: {
  progress: ApplyProgress;
  options: GoalBannerOptions;
  goal: number;
  now: Date;
  onTab: (tab: ApplyTab) => void;
  onSettings: () => void;
}) {
  const startsOn = options.week_start === "sunday" ? 0 : 1;
  const summary = summarizeProgress(stageTimes(progress, options.counts), now, {
    weeks: 1,
    weekStartsOn: startsOn,
  });
  const done = summary.thisWeek;
  const word = STAGE_WORDS[options.counts];
  const first = weekStart(now, startsOn);
  const range = `${shortDate(dayKey(first))} – ${shortDate(dayKey(addDays(first, 6)))}`;
  const meter = (
    <Meter
      value={(done / goal) * 100}
      label="Weekly goal"
      valueText={`${done} of ${goal} ${word}`}
    />
  );
  const actions = options.show_actions && <BannerActions progress={progress} onTab={onTab} />;

  if (options.compact)
    return (
      <Tile aria-label="Weekly goal">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <p className="text-sm text-ink">
            <span className="rt-eyebrow mr-2">This week</span>
            <span className="rt-figure font-display text-xl">{done}</span> of {goal} {word}
          </p>
          <div className="min-w-40 flex-1">{meter}</div>
          {options.show_nudge && (
            <p className="text-sm text-ink-2">
              {goalNudge(done, goal, NUDGE_VERB[options.counts])}
            </p>
          )}
          {actions}
        </div>
      </Tile>
    );

  const waiting = waitingLine(progress);
  const todayIndex = (now.getDay() - startsOn + 7) % 7;
  return (
    <Tile aria-label="Weekly goal">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-center lg:gap-10">
        <div>
          <p className="rt-eyebrow">This week · {range}</p>
          <p className="mt-2 font-display text-3xl leading-tight text-ink">
            <span className="rt-figure">{done}</span> of {goal} {word}
          </p>
          <div className="mt-3">{meter}</div>
          {options.show_days && (
            <ol
              aria-label={`${STAGE_WORDS[options.counts]} each day this week`}
              className="mt-3 grid grid-cols-7 gap-1.5"
            >
              {weekdayNames(startsOn).map((day, i) => {
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
          )}
        </div>
        <div className="space-y-3">
          {options.show_nudge && (
            <p className="text-[15px] font-medium text-ink">
              {goalNudge(done, goal, NUDGE_VERB[options.counts])}
            </p>
          )}
          {options.show_actions && waiting && <p className="text-sm text-ink-2">{waiting}</p>}
          {actions}
          <p className="text-xs text-ink-muted">
            Goal: {goal} {word} a week ·{" "}
            <button type="button" className="rt-link" onClick={onSettings}>
              Change
            </button>
          </p>
        </div>
      </div>
    </Tile>
  );
}
