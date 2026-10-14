import type { AppConfig, JobSettings } from "../api";
import { profileDefaultModel } from "./modelLabel";
import { providerInfo } from "./providers";

export type ModelRole = "light" | "heavy";
export type ModelProvider =
  | "ollama"
  | "ollama-cloud"
  | "lmstudio"
  | "gemini"
  | "anthropic"
  | "openai"
  | "custom"
  | "vertex_ai";
/** How the model is paid for; sets its server's default request concurrency. */
export type ModelPlan = "free" | "paid" | "subscription" | "local";
export type ModelSelection = {
  provider: ModelProvider;
  model_name: string;
  api_format: "openai" | "anthropic";
  base_url: string;
  /** null/absent = guessed from the provider. */
  plan?: ModelPlan | null;
  vertex_project?: string;
  vertex_location?: string;
};
export type AiModels = {
  light: ModelSelection;
  heavy: ModelSelection;
  legacy_light_overrides: Record<string, string>;
  provider_selections?: Partial<Record<ModelRole, Partial<Record<ModelProvider, ModelSelection>>>>;
};

export function modelsFor(settings: JobSettings): AiModels {
  return (
    settings.ai_models ?? {
      light: {
        provider: (settings.model === "claude" ? "anthropic" : settings.model) as ModelProvider,
        model_name: settings.model_name || settings.ollama_model || settings.gemini_model || "",
        api_format: "openai",
        base_url: "",
      },
      heavy: settings.apply.model_selection ?? {
        provider: settings.apply.model_provider,
        model_name: settings.apply.model_name,
        api_format: "openai",
        base_url: "",
      },
      legacy_light_overrides: {},
    }
  );
}

export function withSelection(
  settings: JobSettings,
  role: ModelRole,
  selection: ModelSelection,
): JobSettings {
  const models = modelsFor(settings);
  return {
    ...settings,
    ai_models: {
      ...models,
      [role]: selection,
      provider_selections: {
        ...models.provider_selections,
        [role]: {
          ...models.provider_selections?.[role],
          [models[role].provider]: models[role],
          [selection.provider]: selection,
        },
      },
      legacy_light_overrides: role === "light" ? {} : models.legacy_light_overrides,
    },
    // Keep the Apply request snapshot in sync with unsaved edits.
    apply:
      role === "heavy"
        ? {
            ...settings.apply,
            model_provider: selection.provider,
            model_name: selection.model_name,
            model_selection: selection,
          }
        : settings.apply,
  };
}

/** Restore this role's last complete draft for a provider, including connection fields. */
export function withProvider(
  settings: JobSettings,
  role: ModelRole,
  provider: ModelProvider,
): JobSettings {
  const models = modelsFor(settings);
  if (models[role].provider === provider) return settings;
  return withSelection(
    settings,
    role,
    models.provider_selections?.[role]?.[provider] ?? {
      provider,
      model_name: "",
      base_url: "",
      api_format: "openai",
      plan: null,
      vertex_project: "",
      vertex_location: "",
    },
  );
}

export function selectionProvider(selection: ModelSelection) {
  return providerInfo(selection.provider === "anthropic" ? "claude" : selection.provider);
}

export function selectionDefault(selection: ModelSelection, config: AppConfig | null): string {
  if (["custom", "openai", "vertex_ai"].includes(selection.provider)) return "Enter model name";
  return (
    config?.model_defaults?.[selection.provider] ??
    profileDefaultModel(
      { model: selection.provider === "anthropic" ? "claude" : selection.provider },
      config,
    )
  );
}

export function selectionReady(selection: ModelSelection): boolean {
  if (selection.provider === "vertex_ai")
    return (
      !!selection.model_name.trim() &&
      /^[a-z][a-z0-9-]{4,61}[a-z0-9]$/.test(selection.vertex_project?.trim() ?? "") &&
      /^(global|us|eu|[a-z]+-[a-z]+[0-9]+)$/.test(selection.vertex_location?.trim() ?? "")
    );
  if (selection.provider === "openai") return !!selection.model_name.trim();
  if (selection.provider !== "custom") return true;
  try {
    const url = new URL(selection.base_url);
    return (
      !!selection.model_name.trim() &&
      ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
}

export function selectionLabel(selection: ModelSelection, config: AppConfig | null): string {
  return `${selectionProvider(selection)?.name ?? selection.provider} · ${selection.model_name || selectionDefault(selection, config)}`;
}

export async function customCredentialName(
  role: ModelRole,
  selection: ModelSelection,
): Promise<string> {
  const identity = `${selection.api_format}|${selection.base_url.trim().replace(/\/+$/, "")}`;
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(identity));
  const digest = Array.from(new Uint8Array(hash), (n) => n.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 24);
  return `CUSTOM_${role.toUpperCase()}_${digest}`;
}
