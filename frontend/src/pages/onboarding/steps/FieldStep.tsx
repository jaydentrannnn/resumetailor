import { useEffect, useState } from "react";
import {
  fetchSourceCatalog,
  type OnboardingField,
  type SourceCatalog,
  type SourceField,
} from "../../../api";
import { Button, Tile } from "../../../components/ui";
import { describe } from "../../../lib/errors";
import {
  FIELDS,
  packsForField,
  sourceFieldsFor,
  sourcesForField,
  sourcesFromCatalogPicks,
  suggestedEntries,
  withSourceChoice,
} from "../../../lib/onboarding";
import { useToast } from "../../../lib/toast";
import { useLibraryState } from "../../../state/libraryState";
import { useRunState } from "../../../state/runState";
import { TargetFieldSection } from "../../settings/TargetFieldSection";
import { StepFrame } from "../StepFrame";
import { JobSourcePicker } from "./JobSourcePicker";
/** Step 1: the student's field sets the skill vocabularies and job-board categories. */
export function FieldStep({
  field,
  saving,
  onChoose,
}: {
  field: OnboardingField;
  saving: boolean;
  onChoose: (field: OnboardingField) => void;
}) {
  const toast = useToast();
  const { packs, enabledPacks, setEnabled } = useLibraryState();
  const { settings, setSettings, settingsLoaded } = useRunState();
  const [picked, setPicked] = useState<OnboardingField>(field);
  const [applying, setApplying] = useState(false);
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [catalogFailed, setCatalogFailed] = useState(false);
  const [jobFields, setJobFields] = useState<SourceField[]>(() => sourceFieldsFor(field));
  const [skipped, setSkipped] = useState<Set<string>>(new Set());

  useEffect(() => {
    let live = true;
    fetchSourceCatalog()
      .then((c) => live && setCatalog(c))
      .catch(() => live && setCatalogFailed(true));
    return () => {
      live = false;
    };
  }, []);

  function pickField(next: Exclude<OnboardingField, "">) {
    setPicked(next);
    setJobFields(sourceFieldsFor(next));
    setSkipped(new Set());
  }

  const suggestions = catalog ? suggestedEntries(catalog, jobFields) : [];

  async function choose() {
    if (!picked) return;
    // Re-choosing the same field keeps any tuning done since; only a change resets it.
    if (picked !== field) {
      setApplying(true);
      try {
        await setEnabled(
          packsForField(
            enabledPacks,
            picked,
            packs.map((p) => p.id),
          ),
        );
        const sources =
          catalog && !catalogFailed
            ? sourcesFromCatalogPicks(
                settings.apply.sources,
                suggestions.filter((entry) => !skipped.has(entry.id)),
                picked,
              )
            : sourcesForField(settings.apply.sources, picked);
        setSettings({
          ...settings,
          apply: withSourceChoice(
            settings.apply,
            sources,
            catalog && !catalogFailed ? jobFields : sourceFieldsFor(picked),
          ),
        });
      } catch (err) {
        toast.error("Could not apply your field", describe(err).detail);
        return;
      } finally {
        setApplying(false);
      }
    }
    onChoose(picked);
  }

  return (
    <StepFrame
      title="What are you studying?"
      intro="This picks the skill words ResumeTailor recognises (for example “DCF” and “discounted cash flow”) and which job lists to search."
      saving={saving}
    >
      <div role="radiogroup" aria-labelledby="step-title" className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((option) => (
          <Tile
            as="label"
            padding="sm"
            key={option.id}
            className={`flex cursor-pointer gap-3 ${
              picked === option.id
                ? "border-selected-line bg-selected-row text-accent shadow-[inset_0_0_0_1px_var(--color-selected-line)]"
                : "border-line bg-field! text-ink"
            }`}
          >
            <input
              type="radio"
              name="field"
              className="mt-1"
              checked={picked === option.id}
              onChange={() => pickField(option.id)}
            />
            <span>
              <span className="block text-sm font-semibold">{option.label}</span>
              <span className="mt-1 block text-xs text-ink-muted">{option.description}</span>
            </span>
          </Tile>
        ))}
      </div>
      {picked && catalog && !catalogFailed && (
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
      <TargetFieldSection embedded />
      <div className="flex justify-between border-t border-line pt-4">
        <Button variant="ghost" disabled>
          Back
        </Button>
        <Button
          variant="primary"
          onClick={choose}
          disabled={!picked || !settingsLoaded}
          loading={applying || saving}
        >
          Next
        </Button>
      </div>
    </StepFrame>
  );
}
