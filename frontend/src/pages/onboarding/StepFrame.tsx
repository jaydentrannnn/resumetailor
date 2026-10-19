import { useEffect, useState, type MutableRefObject, type ReactNode } from "react";
import { Button, TileLayout } from "../../components/ui";
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
  /** Where this step sits ("Step 2 of 7"), shown over its title. */
  position?: string;
};

const saved = () => Promise.resolve(true);

/**
 * One wizard step: where it sits, its title and intro, the body in a readable column,
 * and the footer bar every step shares (it stays in view at the bottom of the window).
 * Groups inside a step are ruled apart, as on Profile. Back, Skip and Next all save the
 * page first and stay put when the save fails. Next needs the step
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
    <section aria-labelledby="step-title" className="flex min-h-full flex-col">
      <div className="max-w-3xl flex-1 space-y-5">
        <div>
          {nav.position && <p className="text-xs text-ink-muted">{nav.position}</p>}
          <h2 id="step-title" className="mt-1 font-display text-2xl font-medium text-ink">
            {title}
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-2">{intro}</p>
        </div>
        <TileLayout.Provider value="ruled">{children}</TileLayout.Provider>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
      </div>
      <div className="sticky bottom-(--rt-bar-bottom) mt-8 flex max-w-3xl flex-wrap items-center gap-3 border-t border-line bg-paper py-3">
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
    </section>
  );
}
