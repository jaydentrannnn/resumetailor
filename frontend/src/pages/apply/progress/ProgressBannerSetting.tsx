import type { ApplySettings, ProgressBanner } from "../../../api";
import { Segmented } from "../../../components/ui";
import { activityOptions, goalOptions, pipelineOptions } from "../../../lib/progressOptions";
import { ActivityOptions } from "./ActivityOptions";
import { GoalOptions } from "./GoalOptions";
import { PipelineOptions } from "./PipelineOptions";

const KINDS: { id: ProgressBanner; label: string }[] = [
  { id: "goal", label: "Weekly goal" },
  { id: "activity", label: "Activity" },
  { id: "pipeline", label: "Pipeline" },
  { id: "off", label: "Off" },
];

const NOTES: Record<ProgressBanner, string> = {
  goal: "This week against your goal, day by day.",
  activity: "A day-by-day heatmap of one stage over the dates you pick.",
  pipeline: "How far the postings found in a date range got, and where most of them stop.",
  off: "No banner over the list.",
};

type BannerSettings = Pick<
  ApplySettings,
  "progress_banner" | "weekly_goal" | "goal_banner" | "activity_banner" | "pipeline_banner"
>;

/** Apply settings › Progress banner: which banner sits over the list, and its options. */
export function ProgressBannerSetting({
  apply,
  patch,
}: {
  apply: BannerSettings;
  patch: (fields: Partial<ApplySettings>) => void;
}) {
  const kind = apply.progress_banner ?? "goal";
  return (
    <div className="space-y-4">
      <Segmented
        label="Progress banner"
        items={KINDS}
        value={kind}
        onChange={(id) => patch({ progress_banner: id as ProgressBanner })}
      />
      <p className="text-xs text-ink-muted">{NOTES[kind]}</p>
      {kind === "goal" && (
        <GoalOptions
          goal={apply.weekly_goal ?? 10}
          options={goalOptions(apply)}
          onGoal={(weekly_goal) => patch({ weekly_goal })}
          onChange={(change) => patch({ goal_banner: { ...goalOptions(apply), ...change } })}
        />
      )}
      {kind === "activity" && (
        <ActivityOptions
          options={activityOptions(apply)}
          onChange={(change) =>
            patch({ activity_banner: { ...activityOptions(apply), ...change } })
          }
        />
      )}
      {kind === "pipeline" && (
        <PipelineOptions
          options={pipelineOptions(apply)}
          onChange={(change) =>
            patch({ pipeline_banner: { ...pipelineOptions(apply), ...change } })
          }
        />
      )}
    </div>
  );
}
