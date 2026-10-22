import type { ApplyProgress, PipelineBannerOptions } from "../../../api";
import { Meter, Tile } from "../../../components/ui";
import type { ApplyTab } from "../../../lib/applyPage";
import {
  biggestDrop,
  pipelineHeadline,
  pipelineSteps,
  pipelineWindow,
  stageCounts,
  type PipelineStep,
} from "../../../lib/applyPipeline";
import { BannerActions, CustomizeLink } from "./BannerActions";
import { OutcomeRates, PipelineFunnel, PipelineStrip } from "./PipelineViews";

/** How far the postings found in a date range got, stage by stage, as cards, a funnel or a line. */
export function PipelineBanner({
  progress,
  options,
  now,
  onTab,
  onSettings,
}: {
  progress: ApplyProgress;
  options: PipelineBannerOptions;
  now: Date;
  onTab: (tab: ApplyTab) => void;
  onSettings?: () => void;
}) {
  const dates = pipelineWindow(options, now);
  const steps = pipelineSteps(stageCounts(progress, dates), options.stages);
  const actions = options.show_actions && <BannerActions progress={progress} onTab={onTab} />;

  if (options.style === "compact")
    return (
      <Tile aria-label="Your pipeline">
        <PipelineStrip
          steps={steps}
          label={dates.label}
          showPercent={options.show_percent}
          actions={actions}
        />
      </Tile>
    );

  const drop =
    options.show_drop &&
    biggestDrop(steps, {
      needs_you: progress.needs_you,
      unscreened: dates.from || dates.to ? null : progress.unscreened,
    });
  return (
    <Tile aria-label="Your pipeline">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="rt-eyebrow">Your pipeline · {dates.label}</p>
        {options.show_percent && <p className="text-sm text-ink-2">{pipelineHeadline(steps)}</p>}
      </div>
      {options.style === "funnel" ? (
        <PipelineFunnel steps={steps} showPercent={options.show_percent} />
      ) : (
        <PipelineCards steps={steps} showPercent={options.show_percent} />
      )}
      {(drop || actions || onSettings || !!progress.outcomes?.sent) && (
        <div className="mt-5 flex flex-wrap items-center gap-4 border-t border-line pt-4">
          <OutcomeRates cohort={progress.outcomes} />
          {drop && (
            <p className="min-w-80 flex-1 text-sm text-ink-2">
              <span className="font-semibold text-ink">{drop.title}</span> {drop.detail}
            </p>
          )}
          {actions}
          {onSettings && <CustomizeLink onSettings={onSettings} />}
        </div>
      )}
    </Tile>
  );
}

/** One card per stage: its count, a bar of its share of the first, and its step rate. */
function PipelineCards({ steps, showPercent }: { steps: PipelineStep[]; showPercent: boolean }) {
  const columns = {
    2: "sm:grid-cols-2",
    3: "sm:grid-cols-3",
    4: "sm:grid-cols-4",
    5: "sm:grid-cols-5",
  };
  return (
    <ol
      className={`mt-4 grid grid-cols-2 gap-x-7 gap-y-5 ${columns[steps.length as keyof typeof columns]}`}
    >
      {steps.map((step, i) => (
        <li key={step.stage}>
          <p className="rt-eyebrow">{step.label}</p>
          <p className="mt-2 font-display text-4xl leading-none text-ink">{step.count}</p>
          <Meter
            className="mb-2 mt-3"
            value={step.share}
            label={`${step.label}: ${step.share}% of ${steps[0].label.toLowerCase()}`}
            tone={i === steps.length - 1 ? "accent" : "ink"}
          />
          {showPercent && <p className="text-xs text-ink-muted">{step.rate}</p>}
        </li>
      ))}
    </ol>
  );
}
