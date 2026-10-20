import type { ReactNode } from "react";
import type { PipelineStep } from "../../../lib/applyPipeline";

/** The pipeline as a funnel: one bar per stage, as wide as its share of the first. */
export function PipelineFunnel({
  steps,
  showPercent,
}: {
  steps: PipelineStep[];
  showPercent: boolean;
}) {
  return (
    <ol className="mt-4 space-y-2">
      {steps.map((step, i) => (
        <li
          key={step.stage}
          className="grid grid-cols-[7rem_minmax(0,1fr)_auto] items-center gap-4 text-sm"
        >
          <span className="text-ink-2">{step.label}</span>
          <span className="flex justify-center">
            <span
              aria-hidden
              className={`h-7 rounded-sm ${i === steps.length - 1 ? "bg-accent" : "bg-ink/80"}`}
              style={{ width: `${Math.max(2, step.share)}%` }}
            />
          </span>
          <span className="min-w-36 text-right">
            <span className="font-display text-lg text-ink">{step.count}</span>
            {showPercent && i > 0 && (
              <span className="ml-2 text-xs text-ink-muted">{step.rate}</span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** The pipeline on one line: "Found 198 → Screened in 54 → … · 14%". */
export function PipelineStrip({
  steps,
  label,
  showPercent,
  actions,
}: {
  steps: PipelineStep[];
  label: string;
  showPercent: boolean;
  actions: ReactNode;
}) {
  const last = steps[steps.length - 1];
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
      <p className="rt-eyebrow">Pipeline · {label}</p>
      <ol className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm text-ink-2">
        {steps.map((step, i) => (
          <li key={step.stage} className="flex items-baseline gap-2">
            {i > 0 && <span aria-hidden>→</span>}
            <span>
              {step.label} <span className="font-display text-lg text-ink">{step.count}</span>
            </span>
          </li>
        ))}
      </ol>
      {showPercent && (
        <p className="text-sm font-medium text-accent">
          {last.share}% {last.label.toLowerCase()}
        </p>
      )}
      <div className="ml-auto">{actions}</div>
    </div>
  );
}
