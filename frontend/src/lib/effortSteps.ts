import type { AppConfig } from "../api";
import type { VertexModel } from "../api";
import type { ModelRole, ModelSelection } from "./aiModels";

export type EffortLevel = "low" | "medium" | "high";
/** Keys of `config.EFFORT_STEPS` on the server. */
export type EffortStep = "analysis" | "rewrite" | "expand" | "cover" | "answer";
/** `JobSettings.effort`: null = recommended, one level = every step, a map = Custom. */
export type EffortSetting = EffortLevel | Partial<Record<EffortStep, EffortLevel>> | null;

export const EFFORT_LEVELS: { id: EffortLevel; label: string }[] = [
  { id: "low", label: "Low" },
  { id: "medium", label: "Medium" },
  { id: "high", label: "High" },
];

/** The steps Settings → Advanced offers, in the order people care about them. */
export const EFFORT_STEPS: { id: EffortStep; label: string; help: string; role: ModelRole }[] = [
  {
    id: "rewrite",
    label: "Bullet rewriting",
    help: "Tailoring each resume bullet to the posting. Where effort shows most.",
    role: "light",
  },
  {
    id: "expand",
    label: "Experience descriptions",
    help: "The longer write-up of each role that Apply pastes into forms.",
    role: "light",
  },
  { id: "cover", label: "Cover letter", help: "Writing the cover letter.", role: "light" },
  {
    id: "answer",
    label: "Application answers",
    help: "Free-text answers while Fill completes a form (heavy task model).",
    role: "heavy",
  },
  {
    id: "analysis",
    label: "Job analysis",
    help: "Reading the posting, ranking your bullets, and picking project tech and skills.",
    role: "light",
  },
];

/** Providers that receive the effort setting (`config.forwards_effort`). */
export function receivesEffort(
  selection: ModelSelection,
  vertexModels: VertexModel[] = [],
): boolean {
  if (selection.provider === "vertex_ai")
    return vertexModels.some(
      (m) => m.id === selection.model_name.replace(/^vertex_ai\//, "") && m.reasoning,
    );
  if (selection.provider === "custom") return selection.api_format === "anthropic";
  return ["anthropic", "openai", "gemini"].includes(selection.provider);
}

function providerKey(selection: ModelSelection): string {
  return ["anthropic", "openai", "gemini"].includes(selection.provider)
    ? selection.provider
    : "other";
}

export function recommendedEffort(
  config: AppConfig | null,
  step: EffortStep,
  selection: ModelSelection,
): EffortLevel {
  const level = config?.recommended_effort?.[step]?.[providerKey(selection)];
  return (
    (level as EffortLevel | undefined) ??
    (step === "analysis" || step === "answer" ? "low" : "medium")
  );
}

/** Every step's level as Custom shows it; steps the setting leaves out use `fallback`. */
export function customLevels(
  effort: EffortSetting,
  fallback: (step: EffortStep) => EffortLevel,
): Record<EffortStep, EffortLevel> {
  const levels = {} as Record<EffortStep, EffortLevel>;
  for (const { id } of EFFORT_STEPS) {
    levels[id] = typeof effort === "string" ? effort : (effort?.[id] ?? fallback(id));
  }
  return levels;
}
