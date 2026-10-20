import type { ApplyProgress } from "../../../api";
import { Button } from "../../../components/ui";
import type { ApplyTab } from "../../../lib/applyPage";

/** The work a banner points at: what waits on the applicant, then what is ready to fill. */
export function BannerActions({
  progress,
  onTab,
}: {
  progress: ApplyProgress;
  onTab: (tab: ApplyTab) => void;
}) {
  if (!progress.needs_you && !progress.ready) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {progress.needs_you > 0 && (
        <Button variant="primary" onClick={() => onTab("needs")}>
          Open Needs you ({progress.needs_you})
        </Button>
      )}
      {progress.ready > 0 && (
        <Button
          variant={progress.needs_you > 0 ? "secondary" : "primary"}
          onClick={() => onTab("progress")}
        >
          See {progress.ready} ready to fill
        </Button>
      )}
    </div>
  );
}
