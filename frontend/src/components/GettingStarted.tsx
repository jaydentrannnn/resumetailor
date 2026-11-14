import { Link, useLocation } from "react-router-dom";
import { buttonClass } from "../lib/buttonClass";
import { guideProgress, type GuideStep } from "../lib/guide";
import { toneChipClass } from "../lib/tone";
import { useGuide } from "../state/guideState";
import { Button, Tile } from "./ui";
import { StatusMark } from "./ui/Status";

/**
 * The guide's steps as a list: finished ones ticked, the next one opened up with what to
 * do and a button that goes there, the rest named only. The button is left out on the
 * page the step already points at.
 */
export function GuideSteps({ steps, onNavigate }: { steps: GuideStep[]; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const { next } = guideProgress(steps);
  return (
    <ol className="space-y-3">
      {steps.map((step) => {
        // An optional step is offered as soon as it shows, beside the next required one.
        const current = step.id === next?.id || (!!step.optional && !step.done);
        const tone = step.done ? "done" : current && !step.optional ? "attention" : "muted";
        return (
          <li
            key={step.id}
            className="flex gap-3 text-sm"
            aria-current={step.id === next?.id ? "step" : undefined}
          >
            <span
              aria-hidden="true"
              className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-sm ${toneChipClass(tone)}`}
            >
              <StatusMark tone={tone} />
            </span>
            <div className="min-w-0 flex-1">
              <p className={current ? "font-medium text-ink" : "text-ink-muted"}>
                {step.title}
                {step.optional && <span className="ml-1.5 text-xs text-ink-muted">Optional</span>}
                <span className="sr-only">
                  {step.done ? " (done)" : step.optional ? "" : current ? " (next)" : " (later)"}
                </span>
              </p>
              {current && (
                <>
                  <p className="mt-0.5 text-xs text-ink-muted">{step.detail}</p>
                  {pathname !== step.to && (
                    <Link
                      to={step.to}
                      onClick={onNavigate}
                      className={buttonClass("secondary", "sm", "mt-2")}
                    >
                      {step.action}
                    </Link>
                  )}
                </>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** The Getting started panel (Tailor page, while no run is open). Null when the guide is off. */
export function GettingStarted({ className = "" }: { className?: string }) {
  const guide = useGuide();
  if (!guide.active || !guide.steps) return null;
  const { done, total } = guideProgress(guide.steps);
  return (
    <Tile
      embedded
      aria-label="Getting started"
      title="Getting started"
      meta={`${done} of ${total} done`}
      actions={
        <Button variant="plain" size="sm" onClick={() => void guide.hide()}>
          Hide guide
        </Button>
      }
      className={className}
    >
      <GuideSteps steps={guide.steps} />
    </Tile>
  );
}
