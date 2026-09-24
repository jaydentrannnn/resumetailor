import type { AppConfig, JobSettings } from "../api";

/** The model a profile uses when no model name override is set — mirrors the
 * backend's per-profile default tag (`config.OLLAMA_MODEL` etc.). */
export function profileDefaultModel(
  settings: Pick<JobSettings, "model">,
  config: AppConfig | null,
): string {
  if (!config) return "e.g. gemma4:cloud";
  if (config.ollama_profiles.includes(settings.model)) return config.ollama_model;
  if (config.gemini_profiles.includes(settings.model)) return config.gemini_model;
  if (settings.model === "claude") return "claude-sonnet-5";
  if (settings.model === "lmstudio") return "local-model";
  return "provider:model";
}

/** "profile · model" label for the Tailor tab's model settings, which Prepare also
 * uses (see `daily._job_settings` on the backend). */
export function tailorModelLabel(
  settings: Pick<JobSettings, "model" | "model_name">,
  config: AppConfig | null,
): string {
  const model = settings.model_name || (config ? profileDefaultModel(settings, config) : "");
  return model ? `${settings.model} · ${model}` : settings.model;
}
