import { type StepState, stepState } from "../../lib/stepState";

export interface StepItem {
  id: string;
  label: string;
  /** Quiet mono detail after the label (a duration, "9 / 14"). */
  meta?: string;
}

const DOT: Record<StepState, string> = {
  done: "border-accent bg-accent text-on-accent",
  current: "border-accent text-accent",
  upcoming: "border-line-hover text-ink-muted",
  error: "border-danger bg-danger-soft text-danger",
};

const GLYPH: Record<StepState, string> = { done: "✓", current: "", upcoming: "", error: "!" };

/**
 * A row of numbered steps (wizards, run progress). Clicking a finished step calls
 * `onSelect` when given; steps ahead of the current one are never clickable.
 * `divided` (vertical only) separates the rows with hairlines and right-aligns each
 * step's `meta`, the run-stages list on the Tailor page.
 */
export function Stepper({
  steps,
  current,
  failed,
  onSelect,
  label = "Progress",
  orientation = "horizontal",
  divided = false,
}: {
  steps: StepItem[];
  current: number;
  failed?: number | null;
  onSelect?: (index: number) => void;
  label?: string;
  /** "vertical" stacks the steps for narrow panels (run progress). */
  orientation?: "horizontal" | "vertical";
  /** Vertical only: hairlines between rows and the meta pushed to the right edge. */
  divided?: boolean;
}) {
  const vertical = orientation === "vertical";
  const lined = vertical && divided;
  return (
    <ol
      aria-label={label}
      className={
        lined
          ? "flex flex-col"
          : vertical
            ? "flex flex-col gap-2"
            : "flex flex-wrap items-center gap-x-2 gap-y-2"
      }
    >
      {steps.map((step, index) => {
        const state = stepState(index, current, failed);
        const clickable = onSelect && state === "done";
        const content = (
          <>
            <span
              className={`flex size-[18px] shrink-0 items-center justify-center rounded-sm border font-mono text-[10px] font-medium ${DOT[state]}`}
            >
              {GLYPH[state] || index + 1}
            </span>
            <span
              className={`text-sm ${state === "current" ? "font-semibold text-ink" : "text-ink-muted"}`}
            >
              {step.label}
            </span>
            {step.meta && (
              <span
                className={`font-mono text-xs text-ink-muted ${lined ? "ml-auto pl-3 tabular-nums" : ""}`}
              >
                {step.meta}
              </span>
            )}
          </>
        );
        return (
          <li
            key={step.id}
            className={`flex items-center gap-2 ${lined ? "border-t border-line py-2.5 first:border-t-0" : ""}`}
            aria-current={state === "current" ? "step" : undefined}
          >
            {clickable ? (
              <button
                type="button"
                className={`flex items-center gap-2 rounded-sm px-1 hover:bg-sunken ${lined ? "flex-1" : ""}`}
                onClick={() => onSelect(index)}
              >
                {content}
              </button>
            ) : (
              <span className={`flex items-center gap-2 px-1 ${lined ? "flex-1" : ""}`}>
                {content}
              </span>
            )}
            {!vertical && index < steps.length - 1 && (
              <span aria-hidden="true" className="h-px w-4 bg-line sm:w-8" />
            )}
            {state === "error" && <span className="sr-only">(failed)</span>}
            {state === "done" && <span className="sr-only">(done)</span>}
          </li>
        );
      })}
    </ol>
  );
}
