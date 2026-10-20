import type { ApplySettings, ProgressBanner } from "../../../api";
import { Segmented } from "../../../components/ui";

const KINDS: { id: ProgressBanner; label: string }[] = [
  { id: "goal", label: "Weekly goal" },
  { id: "activity", label: "Activity" },
  { id: "pipeline", label: "Pipeline" },
  { id: "off", label: "Off" },
];

const NOTES: Record<ProgressBanner, string> = {
  goal: "This week's applications against your goal, day by day.",
  activity: "Applications sent each day over the last 13 weeks.",
  pipeline: "How far every found posting got, and where most of them stop.",
  off: "No banner over the list.",
};

/** Apply settings › Progress banner: which banner sits over the list, and the goal. */
export function ProgressBannerSetting({
  apply,
  patch,
}: {
  apply: Pick<ApplySettings, "progress_banner" | "weekly_goal">;
  patch: (fields: Partial<ApplySettings>) => void;
}) {
  const kind = apply.progress_banner ?? "goal";
  return (
    <div className="space-y-3">
      <Segmented
        label="Progress banner"
        items={KINDS}
        value={kind}
        onChange={(id) => patch({ progress_banner: id as ProgressBanner })}
      />
      <p className="text-xs text-ink-muted">{NOTES[kind]}</p>
      {kind === "goal" && (
        <label className="block max-w-56">
          <span className="mb-1 block">Applications a week</span>
          <input
            className="field w-full"
            type="number"
            min={1}
            max={500}
            value={apply.weekly_goal ?? 10}
            onChange={(e) =>
              patch({ weekly_goal: Math.min(500, Math.max(1, Number(e.target.value) || 1)) })
            }
          />
        </label>
      )}
    </div>
  );
}
