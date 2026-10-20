import type { ApplyProgress } from "../../../api";
import { Meter, Tile } from "../../../components/ui";
import type { ApplyTab } from "../../../lib/applyPage";
import { biggestDrop, pipelineSteps } from "../../../lib/applyProgress";
import { BannerActions } from "./BannerActions";

/** How far every found posting got, stage by stage, and where most of them stop. */
export function PipelineBanner({
  progress,
  onTab,
}: {
  progress: ApplyProgress;
  onTab: (tab: ApplyTab) => void;
}) {
  const steps = pipelineSteps(progress);
  const drop = biggestDrop(progress);
  return (
    <Tile aria-label="Your pipeline">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="rt-eyebrow">Your pipeline · all time</p>
        <p className="text-sm text-ink-2">{steps[4].share}% of the postings found were sent.</p>
      </div>
      <ol className="mt-4 grid grid-cols-2 gap-x-7 gap-y-5 sm:grid-cols-5">
        {steps.map((step, i) => (
          <li key={step.label}>
            <p className="rt-eyebrow">{step.label}</p>
            <p className="mt-2 font-display text-4xl leading-none text-ink">{step.count}</p>
            <Meter
              className="mb-2 mt-3"
              value={step.share}
              label={`${step.label}: ${step.share}% of found`}
              tone={i === steps.length - 1 ? "accent" : "ink"}
            />
            <p className="text-xs text-ink-muted">{step.rate}</p>
          </li>
        ))}
      </ol>
      {(drop || progress.needs_you > 0 || progress.ready > 0) && (
        <div className="mt-5 flex flex-wrap items-center gap-4 border-t border-line pt-4">
          {drop && (
            <p className="min-w-80 flex-1 text-sm text-ink-2">
              <span className="font-semibold text-ink">{drop.title}</span> {drop.detail}
            </p>
          )}
          <BannerActions progress={progress} onTab={onTab} />
        </div>
      )}
    </Tile>
  );
}
