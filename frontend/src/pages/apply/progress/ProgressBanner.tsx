import { useMemo } from "react";
import type { ProgressBanner as BannerKind } from "../../../api";
import type { ApplyTab } from "../../../lib/applyPage";
import { summarizeProgress } from "../../../lib/applyProgress";
import { ActivityBanner } from "./ActivityBanner";
import { GoalBanner } from "./GoalBanner";
import { PipelineBanner } from "./PipelineBanner";
import { useApplyProgress } from "./useApplyProgress";

/**
 * The banner over the Apply list, as chosen in Apply settings: the weekly goal, the
 * activity heatmap or the pipeline. Nothing shows until a source has found a posting.
 */
export function ProgressBanner({
  kind,
  goal,
  workspaceId,
  revision,
  onTab,
  onSettings,
}: {
  kind: BannerKind;
  goal: number;
  workspaceId: string;
  revision: number;
  onTab: (tab: ApplyTab) => void;
  onSettings: () => void;
}) {
  const progress = useApplyProgress(workspaceId, revision);
  const summary = useMemo(
    () => (progress ? summarizeProgress(progress.sent, new Date()) : null),
    [progress],
  );
  if (kind === "off" || !progress || !summary || progress.found === 0) return null;
  if (kind === "activity")
    return <ActivityBanner progress={progress} summary={summary} onTab={onTab} />;
  if (kind === "pipeline") return <PipelineBanner progress={progress} onTab={onTab} />;
  return (
    <GoalBanner
      progress={progress}
      summary={summary}
      goal={Math.max(1, goal)}
      now={new Date()}
      onTab={onTab}
      onSettings={onSettings}
    />
  );
}
