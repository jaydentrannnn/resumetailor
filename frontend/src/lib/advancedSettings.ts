import type { JobSettings } from "../api";
import { DEFAULT_SETTINGS } from "../state/runDefaults";

export type AdvancedSettings = Pick<JobSettings, "effort" | "extract_runs" | "max_concurrent_jobs">;

export function withAdvanced(settings: JobSettings, enabled: boolean): JobSettings {
  const values = enabled ? (settings.advanced_settings ?? DEFAULT_SETTINGS) : DEFAULT_SETTINGS;
  return {
    ...settings,
    ai_advanced_enabled: enabled,
    advanced_settings: enabled
      ? settings.advanced_settings
      : {
          effort: settings.effort,
          extract_runs: settings.extract_runs,
          max_concurrent_jobs: settings.max_concurrent_jobs,
        },
    effort: values.effort,
    extract_runs: values.extract_runs,
    max_concurrent_jobs: values.max_concurrent_jobs,
  };
}

export function withEffortMode(
  settings: JobSettings,
  custom: boolean,
  defaults: JobSettings["effort"],
): JobSettings {
  return {
    ...settings,
    effort: custom ? (settings.custom_effort ?? defaults) : null,
    custom_effort: custom ? settings.custom_effort : (settings.effort ?? settings.custom_effort),
  };
}
