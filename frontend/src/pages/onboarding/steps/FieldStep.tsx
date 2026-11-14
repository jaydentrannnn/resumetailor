import { useState } from "react";
import type { OnboardingField } from "../../../api";
import { Tile } from "../../../components/ui";
import { describe } from "../../../lib/errors";
import { SKIP_WARNINGS, studyFieldForTarget } from "../../../lib/onboarding";
import { useRunState } from "../../../state/runState";
import { StepFrame, type StepNav } from "../StepFrame";

/**
 * Step 1: the target field. It steers the writing and the skill words recognised; the
 * job lists it suggests are picked later, on the "Job lists & browser" step.
 */
export function FieldStep({
  nav,
  saveField,
}: {
  nav: StepNav;
  saveField: (field: OnboardingField) => Promise<boolean>;
}) {
  const { config, settingsLoaded, setTargetField } = useRunState();
  const target = config?.target_field ?? null;
  const [error, setError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);

  async function pick(id: string) {
    setChoosing(true);
    setError(null);
    try {
      await setTargetField(id);
    } catch (err) {
      setError(describe(err).detail);
    } finally {
      setChoosing(false);
    }
  }

  return (
    <StepFrame
      title="What field are you targeting?"
      intro="This sets how your bullets are written and the skill words ResumeTailor recognises."
      nav={nav}
      complete={!!target}
      onSave={() => saveField(studyFieldForTarget(target))}
      skipWarning={SKIP_WARNINGS.field}
      error={error}
    >
      <div
        role="radiogroup"
        aria-labelledby="step-title"
        aria-busy={choosing}
        className="grid gap-3 sm:grid-cols-2"
      >
        {(config?.target_fields ?? []).map((option) => (
          <Tile
            as="label"
            padding="sm"
            key={option.id}
            className={`flex cursor-pointer gap-3 ${
              target === option.id
                ? "border-selected-line bg-selected-row text-accent shadow-[inset_0_0_0_1px_var(--color-selected-line)]"
                : "border-line bg-field! text-ink"
            }`}
          >
            <input
              type="radio"
              name="target-field"
              className="mt-1"
              checked={target === option.id}
              disabled={choosing || !settingsLoaded}
              onChange={() => void pick(option.id)}
            />
            <span>
              <span className="block text-sm font-semibold">{option.label}</span>
              <span className="mt-1 block text-xs text-ink-muted">{option.summary}</span>
            </span>
          </Tile>
        ))}
      </div>
    </StepFrame>
  );
}
