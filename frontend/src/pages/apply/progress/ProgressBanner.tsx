import type { ApplySettings } from "../../../api";
import type { ApplyTab } from "../../../lib/applyPage";
import { activityOptions, goalOptions, pipelineOptions } from "../../../lib/progressOptions";
import { ActivityBanner } from "./ActivityBanner";
import { GoalBanner } from "./GoalBanner";
import { PipelineBanner } from "./PipelineBanner";
import { useApplyProgress } from "./useApplyProgress";

/**
 * The banner over the Apply list, as chosen in Settings › Appearance › Progress banner:
 * the weekly goal, the activity heatmap or the pipeline. Nothing shows until a source
 * has found a posting (unless ``preview``).
 */
export function ProgressBanner({
  apply,
  workspaceId,
  revision,
  onTab,
  onSettings,
  preview = false,
}: {
  apply: Pick<
    ApplySettings,
    "progress_banner" | "weekly_goal" | "goal_banner" | "activity_banner" | "pipeline_banner"
  >;
  workspaceId: string;
  revision: number;
  onTab: (tab: ApplyTab) => void;
  onSettings: () => void;
  /** Show the layout even with no postings (customize dialog). */
  preview?: boolean;
}) {
  const progress = useApplyProgress(workspaceId, revision);
  const kind = apply.progress_banner ?? "goal";
  if (kind === "off") return null;
  if (!preview && (!progress || progress.found === 0)) return null;
  const empty = {
    found: 0,
    screened_in: 0,
    tailored: 0,
    autofilled: 0,
    sent: [],
    sent_total: 0,
    needs_you: 0,
    ready: 0,
    unscreened: 0,
    postings: [],
  };
  const data = progress ?? empty;
  const now = new Date();
  if (kind === "activity")
    return (
      <ActivityBanner
        progress={data}
        options={activityOptions(apply)}
        now={now}
        onTab={onTab}
        onSettings={onSettings}
      />
    );
  if (kind === "pipeline")
    return (
      <PipelineBanner
        progress={data}
        options={pipelineOptions(apply)}
        now={now}
        onTab={onTab}
        onSettings={onSettings}
      />
    );
  return (
    <GoalBanner
      progress={data}
      options={goalOptions(apply)}
      goal={Math.max(1, apply.weekly_goal ?? 10)}
      now={now}
      onTab={onTab}
      onSettings={onSettings}
    />
  );
}
