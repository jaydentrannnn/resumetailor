import type { ApplySettings } from "../../../api";
import type { ApplyTab } from "../../../lib/applyPage";
import { activityOptions, goalOptions, pipelineOptions } from "../../../lib/progressOptions";
import { ActivityBanner } from "./ActivityBanner";
import { GoalBanner } from "./GoalBanner";
import { PipelineBanner } from "./PipelineBanner";
import { useApplyProgress } from "./useApplyProgress";

/**
 * The banner over the Apply list, as chosen and set up in Apply settings › Progress
 * banner: the weekly goal, the activity heatmap or the pipeline. Nothing shows until a
 * source has found a posting.
 */
export function ProgressBanner({
  apply,
  workspaceId,
  revision,
  onTab,
  onSettings,
}: {
  apply: Pick<
    ApplySettings,
    "progress_banner" | "weekly_goal" | "goal_banner" | "activity_banner" | "pipeline_banner"
  >;
  workspaceId: string;
  revision: number;
  onTab: (tab: ApplyTab) => void;
  onSettings: () => void;
}) {
  const progress = useApplyProgress(workspaceId, revision);
  const kind = apply.progress_banner ?? "goal";
  if (kind === "off" || !progress || progress.found === 0) return null;
  const now = new Date();
  if (kind === "activity")
    return (
      <ActivityBanner
        progress={progress}
        options={activityOptions(apply)}
        now={now}
        onTab={onTab}
      />
    );
  if (kind === "pipeline")
    return (
      <PipelineBanner
        progress={progress}
        options={pipelineOptions(apply)}
        now={now}
        onTab={onTab}
      />
    );
  return (
    <GoalBanner
      progress={progress}
      options={goalOptions(apply)}
      goal={Math.max(1, apply.weekly_goal ?? 10)}
      now={now}
      onTab={onTab}
      onSettings={onSettings}
    />
  );
}
