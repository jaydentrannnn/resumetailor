import { type StepState, stepState } from "../../lib/stepState";

export interface StepItem {
  id: string;
  label: string;
}

const DOT: Record<StepState, string> = {
  done: "border-accent bg-accent text-on-accent",
  current: "border-accent bg-accent-soft text-accent",
  upcoming: "border-line bg-panel text-ink-muted",
  error: "border-danger bg-danger-soft text-danger",
};

const GLYPH: Record<StepState, string> = { done: "✓", current: "", upcoming: "", error: "!" };

/**
 * A row of numbered steps (wizards, run progress). Clicking a finished step calls
 * `onSelect` when given; steps ahead of the current one are never clickable.
 */
export function Stepper({
  steps,
  current,
  failed,
  onSelect,
  label = "Progress",
  orientation = "horizontal",
}: {
  steps: StepItem[];
  current: number;
  failed?: number | null;
  onSelect?: (index: number) => void;
  label?: string;
  /** "vertical" stacks the steps for narrow panels (run progress). */
  orientation?: "horizontal" | "vertical";
}) {
  const vertical = orientation === "vertical";
  return (
    <ol
      aria-label={label}
      className={vertical ? "flex flex-col gap-2" : "flex flex-wrap items-center gap-x-2 gap-y-2"}
    >
      {steps.map((step, index) => {
        const state = stepState(index, current, failed);
        const clickable = onSelect && state === "done";
        const content = (
          <>
            <span
              className={`flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${DOT[state]}`}
            >
              {GLYPH[state] || index + 1}
            </span>
            <span
              className={`text-sm ${state === "current" ? "font-semibold text-ink" : "text-ink-muted"}`}
            >
              {step.label}
            </span>
          </>
        );
        return (
          <li
            key={step.id}
            className="flex items-center gap-2"
            aria-current={state === "current" ? "step" : undefined}
          >
            {clickable ? (
              <button
                type="button"
                className="flex items-center gap-2 rounded-md px-1 hover:bg-paper"
                onClick={() => onSelect(index)}
              >
                {content}
              </button>
            ) : (
              <span className="flex items-center gap-2 px-1">{content}</span>
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
