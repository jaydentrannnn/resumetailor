import { useEffect, useRef, useState } from "react";
import {
  fetchSourceCatalog,
  type OnboardingField,
  type SourceCatalog,
  type SourceField,
} from "../../../api";
import { Tile } from "../../../components/ui";
import { describe } from "../../../lib/errors";
import {
  SKIP_WARNINGS,
  sourceFieldsForTarget,
  sourcesFromCatalogPicks,
  studyFieldForTarget,
  suggestedEntries,
  withSourceChoice,
} from "../../../lib/onboarding";
import { useRunState } from "../../../state/runState";
import { StepFrame, type StepNav } from "../StepFrame";
import { JobSourcePicker } from "./JobSourcePicker";

/**
 * Step 1: the target field. It steers the writing and preselects which job lists to
 * search.
 */
export function FieldStep({
  nav,
  saveField,
}: {
  nav: StepNav;
  saveField: (field: OnboardingField) => Promise<boolean>;
}) {
  const { config, settings, setSettings, settingsLoaded, setTargetField, flushSettings } =
    useRunState();
  const target = config?.target_field ?? null;
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [jobFields, setJobFields] = useState<SourceField[]>(() =>
    settings.apply.fields?.length ? settings.apply.fields : sourceFieldsForTarget(target),
  );
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);
  const seeded = useRef(false);

  useEffect(() => {
    let live = true;
    fetchSourceCatalog()
      .then((c) => live && setCatalog(c))
      .catch(() => undefined); // no catalog: job lists are chosen later on Applications
    return () => {
      live = false;
    };
  }, []);

  // Coming back to this step: lists the student unticked before stay unticked.
  useEffect(() => {
    if (seeded.current || !catalog || !settingsLoaded) return;
    seeded.current = true;
    if (!settings.apply.fields?.length) return;
    const have = new Set(settings.apply.sources.map((s) => s.catalog_id));
    setSkipped(
      new Set(
        suggestedEntries(catalog, jobFields)
          .filter((e) => !have.has(e.id))
          .map((e) => e.id),
      ),
    );
  }, [catalog, settingsLoaded, settings.apply, jobFields]);

  async function pick(id: string) {
    setChoosing(true);
    setError(null);
    try {
      await setTargetField(id);
      setJobFields(sourceFieldsForTarget(id));
      setSkipped(new Set());
    } catch (err) {
      setError(describe(err).detail);
    } finally {
      setChoosing(false);
    }
  }

  const suggestions = catalog ? suggestedEntries(catalog, jobFields) : [];

  async function save(): Promise<boolean> {
    if (catalog && target) {
      const sources = sourcesFromCatalogPicks(
        settings.apply.sources,
        suggestions.filter((entry) => !skipped.has(entry.id)),
        studyFieldForTarget(target),
      );
      setSettings({ ...settings, apply: withSourceChoice(settings.apply, sources, jobFields) });
    }
    if (!(await flushSettings())) {
      setError("Could not save your job lists. Try again.");
      return false;
    }
    return saveField(studyFieldForTarget(target));
  }

  return (
    <StepFrame
      title="What field are you targeting?"
      intro="This sets how your bullets are written, the skill words ResumeTailor recognises, and which job lists to search."
      nav={nav}
      complete={!!target}
      onSave={save}
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
      {target && catalog && (
        <JobSourcePicker
          fields={jobFields}
          onFields={(next) => {
            setJobFields(next);
            setSkipped(new Set());
          }}
          suggestions={suggestions}
          skipped={skipped}
          onToggle={(id) =>
            setSkipped((prev) => {
              const next = new Set(prev);
              if (!next.delete(id)) next.add(id);
              return next;
            })
          }
        />
      )}
    </StepFrame>
  );
}
