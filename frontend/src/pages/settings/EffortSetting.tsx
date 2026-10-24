import { Segmented, SettingRow } from "../../components/ui";
import { modelsFor } from "../../lib/aiModels";
import {
  customLevels,
  EFFORT_LEVELS,
  EFFORT_STEPS,
  receivesEffort,
  recommendedEffort,
  type EffortStep,
} from "../../lib/effortSteps";
import { useRunState } from "../../state/runState";
import { SELECT_WIDTH } from "./selectWidth";
import { useVertexConnection } from "./useVertexConnection";
import { withEffortMode } from "../../lib/advancedSettings";

/**
 * Reasoning effort, Recommended or Custom per step (`JobSettings.effort`). Only Custom
 * lists the steps; returning to it restores the last Custom draft.
 */
export function EffortSetting() {
  const { settings, setSettings, config } = useRunState();
  const models = modelsFor(settings);
  const vertex = useVertexConnection(
    [models.light, models.heavy].some((m) => m.provider === "vertex_ai"),
  );
  const usesEffort = (role: "light" | "heavy") => receivesEffort(models[role], vertex.models);
  const custom = settings.effort != null;
  const recommended = (step: EffortStep) =>
    recommendedEffort(config, step, models[EFFORT_STEPS.find((s) => s.id === step)!.role]);
  const levels = customLevels(settings.effort, recommended);
  const note = ignoredNote(usesEffort("light"), usesEffort("heavy"));

  return (
    <>
      <SettingRow
        label="Reasoning effort"
        layout="action"
        description="How much the model thinks before answering. Higher can word things better but is slower and costs more."
      >
        <Segmented
          label="Reasoning effort"
          items={[
            { id: "recommended", label: "Recommended" },
            { id: "custom", label: "Custom" },
          ]}
          value={custom ? "custom" : "recommended"}
          onChange={(id) => {
            if ((id === "custom") === custom) return;
            setSettings(withEffortMode(settings, id === "custom", customLevels(null, recommended)));
          }}
        />
      </SettingRow>
      {custom && (
        <div className="space-y-3 pb-4">
          {EFFORT_STEPS.filter(
            (step) => models[step.role].provider !== "vertex_ai" || usesEffort(step.role),
          ).map((step) => (
            <label
              key={step.id}
              className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-6"
            >
              <span className="min-w-0 text-sm">
                {step.label}
                <span className="block text-xs text-ink-muted">{step.help}</span>
              </span>
              <select
                className={`field ${SELECT_WIDTH}`}
                aria-label={`${step.label} effort`}
                value={levels[step.id]}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    effort: { ...levels, [step.id]: e.target.value },
                  })
                }
              >
                {EFFORT_LEVELS.map((level) => (
                  <option key={level.id} value={level.id}>
                    {level.label}
                    {level.id === recommended(step.id) ? " (recommended)" : ""}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {note && <p className="text-xs text-ink-muted">{note}</p>}
        </div>
      )}
    </>
  );
}

/** Which of the chosen task models drop the setting (only Claude, OpenAI and Gemini use it). */
function ignoredNote(light: boolean, heavy: boolean): string | null {
  const why = "Reasoning effort is available only for models that support it.";
  if (!light && !heavy) return `Neither of your task models uses these settings. ${why}`;
  if (!light)
    return `Your light task model ignores these settings; only Application answers use one. ${why}`;
  if (!heavy) return `Your heavy task model ignores the Application answers setting. ${why}`;
  return null;
}
