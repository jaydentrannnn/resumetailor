/** App config, saved settings, workspaces, setup checks, secrets, data, updates, onboarding. */

import { apiError, request } from "./core";
import type { JobSettings } from "./jobs";
import type { TemplateInfo } from "./templates";

export type AppConfig = {
  pages: number;
  experience: number;
  projects: number;
  model_profiles: string[];
  /** Server-side OLLAMA_MODEL / OLLAMA_BASE_URL defaults, shown when no override is set. */
  ollama_model: string;
  ollama_base_url: string;
  /** Profiles with at least one Ollama-routed stage (the tag field applies to these). */
  ollama_profiles: string[];
  /** Server-side GEMINI_MODEL / GEMINI_BASE_URL defaults, mirroring the Ollama pair. */
  gemini_model: string;
  gemini_base_url: string;
  /** Profiles with at least one Gemini-routed stage (the tag field applies to these). */
  gemini_profiles: string[];
  /** Whether a credential is present for each origin that requires one (e.g. "gemini").
   * Booleans only — never the key value itself. */
  provider_keys: Record<string, boolean>;
  effort_options: string[];
  pdf_backend: string;
  calibration_source: string;
  /** Non-null only when a calibration file existed but was rejected as implausible. */
  calibration_rejection: string | null;
  chars_per_line: number;
  lines_per_page: number;
  /** Soft min / hard max character band the rewrite prompt targets for a two-line bullet. */
  bullet_char_soft_min: number;
  bullet_char_max: number;
  tag_vocabulary: string[];
  contact_name: string | null;
  fill_target: number;
  initial_bullet_share: number;
  /** Server default share; null means unweighted. */
  experience_bullet_share: number | null;
  /** Server default per-entry cap; null means uncapped. */
  max_bullets_per_entry: number | null;
  /** Shipped default style blocks for the Tailor tab's prompt editors. */
  rewrite_style_default: string;
  expand_style_default: string;
  cover_style_default: string;
  /** Locked safety rules shown read-only beside each style editor. */
  rewrite_core_rules: string;
  expand_core_rules: string;
  cover_core_rules: string;
  target_field?: string | null;
  target_field_summary?: string;
  target_fields?: { id: string; label: string; summary: string; packs?: string[] }[];
  effective_vocabulary_packs?: string[];
  active_workspace_id: string | null;
  active_workspace_label: string | null;
  /** True once, on the first /api/config response after a legacy-layout migration. */
  migrated_from_legacy: boolean;
};

export type SettingsResponse = {
  workspace_id: string | null;
  settings: JobSettings;
  /** True when settings.json did not exist yet and JobSettings defaults were served. */
  seeded: boolean;
  target_field?: string | null;
};

export type Workspace = {
  id: string;
  label: string;
  created_at: string;
  is_active: boolean;
  has_master_resume: boolean;
  has_template: boolean;
};

export type WorkspaceListResponse = {
  entries: Workspace[];
  active_id: string | null;
};

export type WorkspaceActivateResponse = {
  ok: boolean;
  active_id: string;
  entries: Workspace[];
  config: AppConfig;
  settings: JobSettings;
  template: TemplateInfo;
};

export function fetchConfig(): Promise<AppConfig> {
  /** Load UI defaults and the master resume's tag vocabulary. */
  return request<AppConfig>("/api/config");
}

export function fetchSettings(): Promise<SettingsResponse> {
  /** Load the active profile's saved run defaults. */
  return request<SettingsResponse>("/api/settings");
}

export function saveTargetField(targetField: string | null): Promise<AppConfig> {
  return request<AppConfig>("/api/settings/target-field", {
    method: "PUT",
    body: JSON.stringify({ target_field: targetField }),
  });
}

export function saveSettings(settings: JobSettings): Promise<SettingsResponse> {
  /** Persist new run defaults for the active profile. */
  return request<SettingsResponse>("/api/settings", {
    method: "PUT",
    body: JSON.stringify({ settings }),
  });
}

export function fetchWorkspaces(): Promise<WorkspaceListResponse> {
  /** List every registered profile and which one is active. */
  return request<WorkspaceListResponse>("/api/workspaces");
}

export function createWorkspace(
  label: string,
  copyFrom?: string | null,
): Promise<WorkspaceListResponse> {
  /** Register a new profile, or duplicate `copyFrom`'s resume/template/settings. */
  return request<WorkspaceListResponse>("/api/workspaces", {
    method: "POST",
    body: JSON.stringify({ label, copy_from: copyFrom ?? null }),
  });
}

export function activateWorkspace(id: string): Promise<WorkspaceActivateResponse> {
  /** Switch the active profile; returns fresh config/settings/template in one call. */
  return request<WorkspaceActivateResponse>(`/api/workspaces/${encodeURIComponent(id)}/activate`, {
    method: "POST",
  });
}

export function renameWorkspace(id: string, label: string): Promise<WorkspaceListResponse> {
  /** Rename a profile. Its on-disk directory never moves. */
  return request<WorkspaceListResponse>(`/api/workspaces/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ label }),
  });
}

export function deleteWorkspace(id: string): Promise<WorkspaceListResponse> {
  /** Delete a profile. Refuses the active profile and the last remaining one. */
  return request<WorkspaceListResponse>(`/api/workspaces/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export interface CacheUsage {
  files: number;
  bytes: number;
  max_bytes: number;
}

export interface SetupItem {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
  fix: { label: string; to: string };
  optional: boolean;
}

export interface SetupStatus {
  items: SetupItem[];
  ready: boolean;
  remaining: number;
}

export function fetchSetupStatus(): Promise<SetupStatus> {
  /** Prerequisites checklist for the header pill; never makes a model call. */
  return request("/api/setup-status");
}

export interface SecretState {
  name: string;
  set: boolean;
  /** "env" (from .env / the environment), "saved" (keychain), or null. */
  source: "env" | "saved" | null;
}

export function fetchSecrets(): Promise<{ backend: string; secrets: SecretState[] }> {
  /** Which API keys are set; values are never returned. */
  return request("/api/secrets");
}

export function saveSecret(name: string, value: string): Promise<SecretState> {
  return request(`/api/secrets/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ value }),
  });
}

export function deleteSecret(name: string): Promise<SecretState> {
  return request(`/api/secrets/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export interface CheckResult {
  ok: boolean;
  detail: string;
  model?: string;
  backend?: string;
}

export function testModel(
  settings: JobSettings,
  target: "tailor" | "autofill" = "tailor",
): Promise<CheckResult> {
  /** One tiny model call with these settings (a fraction of a cent on paid APIs). */
  return request("/api/models/test", {
    method: "POST",
    body: JSON.stringify({ settings, target }),
  });
}

export function fetchLocalModels(
  origin: "ollama" | "lmstudio",
): Promise<{ reachable: boolean; base_url: string; models: string[]; detail: string }> {
  return request(`/api/models/local?origin=${origin}`);
}

export function testPdf(): Promise<CheckResult> {
  return request("/api/pdf/test", { method: "POST" });
}

export interface DataInfo {
  workspace_id: string | null;
  data_dir: string;
  templates_dir: string;
  output_dir: string;
  data_bytes: number;
  output_bytes: number;
}

export function fetchDataInfo(): Promise<DataInfo> {
  return request("/api/data/info");
}

export function exportDataUrl(includeOutput: boolean): string {
  return `/api/data/export.zip?include_output=${includeOutput}`;
}

export async function importData(file: File): Promise<{ id: string; label: string }> {
  /** Create a new profile from an export zip; existing profiles are never touched. */
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/data/import", { method: "POST", body: form });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

export function resetData(confirm: string): Promise<{ trash: string }> {
  return request("/api/data/reset", { method: "POST", body: JSON.stringify({ confirm }) });
}

export function fetchHealth(): Promise<{ app: string; ok: boolean; version: string }> {
  return request("/api/health");
}

/** In-app update state (desktop app only; `supported` is false in dev and Docker). */
export type UpdateState =
  | "idle"
  | "checking"
  | "available"
  | "up_to_date"
  | "downloading"
  | "ready"
  | "waiting"
  | "installing"
  | "error";

export type UpdateStatus = {
  supported: boolean;
  current: string | null;
  state: UpdateState;
  available: { version: string; notes: string; date: string } | null;
  pct: number | null;
  last_checked: string | null;
  error: string | null;
  waiting_for: string | null;
  backup: string | null;
};

export function fetchUpdateStatus(): Promise<UpdateStatus> {
  return request("/api/update");
}

export function checkForUpdate(): Promise<UpdateStatus> {
  return request("/api/update/check", { method: "POST" });
}

/** Download the update; it installs (and the app restarts) once nothing is running. */
export function installUpdate(): Promise<UpdateStatus> {
  return request("/api/update/install", { method: "POST" });
}

export function fetchCacheUsage(): Promise<CacheUsage> {
  return request("/api/cache");
}

export function clearCache(): Promise<{ removed: number; freed: number }> {
  return request("/api/cache", { method: "DELETE" });
}

export type OnboardingField = "" | "cs" | "business" | "engineering" | "other";

export type OnboardingStepId =
  "field" | "tools" | "resume" | "personal" | "content" | "application" | "review" | "done";

export interface OnboardingState {
  step: OnboardingStepId;
  field: OnboardingField;
  completed: boolean;
  skipped: boolean;
  /** Steps the student skipped; the Review step marks them. */
  skipped_steps: OnboardingStepId[];
  /** "Start from scratch" on the Resume step (no upload, step answered). */
  resume_from_scratch: boolean;
  updated_at: string;
}

/** Where the first-run wizard left off for the active profile. */
export function getOnboarding(): Promise<OnboardingState> {
  return request("/api/onboarding");
}

export function putOnboarding(
  patch: Partial<
    Pick<
      OnboardingState,
      "step" | "field" | "completed" | "skipped" | "skipped_steps" | "resume_from_scratch"
    >
  >,
): Promise<OnboardingState> {
  return request("/api/onboarding", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}
