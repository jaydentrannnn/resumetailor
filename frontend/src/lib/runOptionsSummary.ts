import type { AppConfig, JobSettings } from "../api";
import { profileDefaultModel } from "./modelLabel";
import { modelsFor, selectionDefault, selectionProvider } from "./aiModels";
import { providerInfo } from "./providers";

/** What the collapsed Options tile shows, one plain value per row. */
export interface RunOptionsSummary {
  pages: string;
  coverLetter: string;
  /** Provider name ("Ollama"), or the raw profile id when it is not a known provider. */
  provider: string;
  /** Model tag shown in mono beside the provider; null while it is only a placeholder. */
  modelName: string | null;
  /** Null until the app config has loaded. */
  pageFit: string | null;
}

const TONE_LABEL: Record<string, string> = {
  formal: "Formal",
  direct: "Direct",
  conversational: "Conversational",
  mirror: "Match the posting",
};

/**
 * The run options reduced to the four facts the Tailor page summarises before the form
 * is opened: page count, cover letter (with its tone when one is set), the model in use
 * and whether page fit is measured for this template or estimated.
 */
export function runOptionsSummary(
  settings: JobSettings,
  config: AppConfig | null,
): RunOptionsSummary {
  const coverOn = settings.cover_letter && !settings.no_cover_letter;
  const tone = TONE_LABEL[settings.cover_angles.tone] ?? "";
  const light = modelsFor(settings).light;
  const modelName = settings.ai_models
    ? light.model_name || selectionDefault(light, config)
    : settings.model_name || profileDefaultModel(settings, config);
  return {
    pages: `${settings.pages} page${settings.pages === 1 ? "" : "s"}`,
    coverLetter: coverOn ? (tone ? `On · ${tone}` : "On") : "Off",
    provider: settings.ai_models
      ? (selectionProvider(light)?.name ?? light.provider)
      : (providerInfo(settings.model)?.name ?? settings.model),
    modelName:
      modelName && !modelName.startsWith("e.g.") && modelName !== "Enter model name"
        ? modelName
        : null,
    pageFit: config ? (config.calibration_source === "fallback" ? "Estimated" : "Measured") : null,
  };
}
