import { useEffect, useState, type MutableRefObject, type ReactNode } from "react";
import { Button, Tile } from "../../components/ui";
import { useConfirm } from "../../state/confirmState";

/** What the wizard hands every step: where Back/Skip/Next go, and the save hook. */
export type StepNav = {
  onBack?: () => void;
  onNext: () => void;
  onSkip: () => void;
  /** The wizard is writing its progress. */
  saving: boolean;
  /** Filled with the step's save so the stepper can save before jumping. */
  saveRef: MutableRefObject<() => Promise<boolean>>;
};

const saved = () => Promise.resolve(true);

/**
 * One wizard step: title, body and the footer every step shares. Back, Skip and Next
 * all save the page first and stay put when the save fails. Next needs the step
 * complete; Skip is for an incomplete step (greyed once complete) and warns first.
 */
export function StepFrame({
  title,
  intro,
  children,
  nav,
  complete,
  onSave = saved,
  skipWarning,
  nextLabel = "Next",
  error,
}: {
  title: string;
  intro: string;
  children: ReactNode;
  nav: StepNav;
  complete: boolean;
  onSave?: () => Promise<boolean>;
  /** What stops working if this step is skipped; omitted = no Skip button. */
  skipWarning?: string;
  nextLabel?: string;
  error?: string | null;
}) {
  const { confirm } = useConfirm();
  const [moving, setMoving] = useState(false);
  const busy = moving || nav.saving;

  useEffect(() => {
    nav.saveRef.current = onSave;
  });

  async function move(go: () => void) {
    setMoving(true);
    try {
      if (await onSave()) go();
    } finally {
      setMoving(false);
    }
  }

  async function skip() {
    const ok = await confirm({
      title: "Skip this step?",
      message: `${skipWarning} You can finish it later from Profile or Settings.`,
      confirmLabel: "Skip",
    });
    if (ok) await move(nav.onSkip);
  }

  return (
    <Tile aria-labelledby="step-title" className="space-y-4">
      <div>
        <h2 id="step-title" className="rt-tile-title">
          {title}
        </h2>
        <p className="mt-1 text-sm text-ink-muted">{intro}</p>
      </div>
      {children}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button
          variant="ghost"
          onClick={() => nav.onBack && void move(nav.onBack)}
          disabled={!nav.onBack || busy}
        >
          Back
        </Button>
        {skipWarning !== undefined && (
          <Button
            variant="ghost"
            className="ml-auto"
            onClick={() => void skip()}
            disabled={complete || busy}
            title={complete ? "This step is complete" : undefined}
          >
            Skip
          </Button>
        )}
        <Button
          variant="primary"
          className={skipWarning === undefined ? "ml-auto" : undefined}
          onClick={() => void move(nav.onNext)}
          disabled={!complete}
          loading={busy}
          title={complete ? undefined : "Fill in the required fields first, or skip this step"}
        >
          {nextLabel}
        </Button>
      </div>
    </Tile>
  );
}
