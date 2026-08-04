/** Shared types and fetch helpers for the ResumeTailor API. */

export type ContactField = "location" | "email" | "phone" | "linkedin" | "github";

export type IncludeOptions = {
  /** Ordered contact-line fields, name excluded (it always renders first). Omitting a
   * field both hides it and shortens the line. Null keeps the active template's order. */
  contact_fields: ContactField[] | null;
  gpa: boolean;
  coursework: boolean;
  /** Experience/project ids omitted from this run entirely. */
  exclude_experience: string[];
  exclude_projects: string[];
};

export type JobSettings = {
  pages: number;
  experience: number | null;
  projects: number | null;
  model: string;
  /** Ollama tag for every Ollama-routed stage; null uses the server's OLLAMA_MODEL. */
  ollama_model: string | null;
  /** Gemini tag for every Gemini-routed stage; null uses the server's GEMINI_MODEL. */
  gemini_model: string | null;
  rewrite_model: string | null;
  expand_model: string | null;
  effort: "low" | "medium" | "high" | null;
  no_semantic: boolean;
  no_widow_repair: boolean;
  no_verb_repair: boolean;
  /** Combine near-duplicate bullets within an entry; only fires if the page overflows. */
  merge: boolean;
  no_cache: boolean;
  /** Skip generating expanded experience descriptions for application forms. */
  no_expand: boolean;
  /** Skip LLM selection of project tech tags and coursework (budget-only truncation). */
  no_facets: boolean;
  /** Render projects without their link label or hyperlink. */
  no_project_links: boolean;
  /** Page-fill fraction (0.80–0.95); null uses the server default. */
  fill_target: number | null;
  /** First-draft bullet-share ceiling (0.30–1.00); null uses the server default. */
  initial_bullet_share: number | null;
  /** Fraction of overall selected bullets given to experience (0.00–1.00), budgeted
   * separately from projects; null means unweighted (one flat relevance-ranked pool). */
  experience_bullet_share: number | null;
  /** Cap on bullets any single job or project may take; null means uncapped. */
  max_bullets_per_entry: number | null;
  /** What to leave out — contact fields/order, GPA, coursework, whole entries. */
  include: IncludeOptions;
};

export type ProgressEvent = {
  stage: string;
  message: string;
  detail: Record<string, unknown>;
};

export type SectionSummary = {
  label: string;
  kept: number;
  total: number;
  rewritten: number;
};

export type KeywordGap = {
  canonical: string;
  phrase: string;
  importance: string;
  reason: "no_evidence" | "untagged_evidence" | "near_miss";
  evidence: string[];
};

export type RunReport = {
  title: string;
  seniority: string;
  coverage_matched: number;
  coverage_total: number;
  missing_must_haves: string[];
  unmatched_canonicals: string[][];
  gaps: KeywordGap[];
  model: string;
  semantic_used: boolean;
  bullets_selected: number;
  bullets_total: number;
  experience: SectionSummary[];
  projects: SectionSummary[];
  dropped: string[];
  pages: number;
  pages_are_estimated: boolean;
  iterations: number;
  widows_repaired: number;
  widows_remaining: number;
  verbs_diversified: number;
  verb_collisions_remaining: number;
  warnings: string[];
  out_path: string;
  pdf_backend: string;
  calibration_source: string;
};

export type ExpandedEntry = {
  entry_key: string;
  title: string;
  company: string;
  location: string;
  start: string;
  end: string;
  bullets: string[];
  char_count: number;
  warnings: string[];
  on_resume: boolean;
};

export type Expansion = {
  entries: ExpandedEntry[];
  warnings: string[];
  model: string;
  char_limit: number;
};

export type JobStatus = {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  queue_position: number | null;
  error: string | null;
  report: RunReport | null;
  expansion: Expansion | null;
  events: ProgressEvent[];
};

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
  chars_per_line: number;
  lines_per_page: number;
  tag_vocabulary: string[];
  contact_name: string | null;
  fill_target: number;
  initial_bullet_share: number;
  /** Server default share; null means unweighted. */
  experience_bullet_share: number | null;
  /** Server default per-entry cap; null means uncapped. */
  max_bullets_per_entry: number | null;
  active_workspace_id: string | null;
  active_workspace_label: string | null;
  /** True once, on the first /api/config response after a legacy-layout migration. */
  migrated_from_legacy: boolean;
};

export type ResumeOutlineEntry = {
  id: string;
  label: string;
  bullets: number;
};

export type ResumeOutline = {
  /** Which of location/email/phone/linkedin/github are non-empty in the master resume. */
  available_contact_fields: string[];
  /** The active template profile's order, used when `include.contact_fields` is null. */
  default_contact_order: string[];
  has_gpa: boolean;
  /** Whether GPA is currently shown for any entry — seeds the tile from the resume's
   * existing behaviour rather than silently flipping it on the next run. */
  gpa_currently_shown: boolean;
  has_coursework: boolean;
  experience: ResumeOutlineEntry[];
  projects: ResumeOutlineEntry[];
  /** A template with no Projects section should not offer project checkboxes or the
   * link toggle. */
  sections_enabled: Record<string, boolean>;
};

export type SettingsResponse = {
  workspace_id: string | null;
  settings: JobSettings;
  /** True when settings.json did not exist yet and JobSettings defaults were served. */
  seeded: boolean;
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

export type ValidateResponse = {
  ok: boolean;
  errors: string[];
  summary: Record<string, unknown> | null;
};

export type TemplateFileInfo = {
  exists: boolean;
  path: string;
  size_bytes: number | null;
  modified_at: string | null;
};

export type CalibrationInfo = {
  source: string;
  chars_per_line: number;
  lines_per_page: number;
  stale: boolean;
  message: string | null;
};

export type TemplateProfileSummary = {
  exists: boolean;
  schema_version: number | null;
  enabled: Record<string, boolean>;
  warnings: string[];
  contact_separator: string | null;
};

export type TemplateInfo = {
  baseline: TemplateFileInfo;
  tagged: TemplateFileInfo;
  experience_entries: number;
  project_entries: number;
  bullets: number;
  calibration: CalibrationInfo;
  preview_available: boolean;
  profile: TemplateProfileSummary;
  active_library_id: string | null;
  active_label: string | null;
};

export type TemplateBuildResponse = {
  ok: boolean;
  log: string;
  info: TemplateInfo | null;
};

export type TemplateLibraryEntry = {
  id: string;
  label: string;
  created_at: string;
  source_filename: string | null;
  size_bytes: number | null;
  has_profile: boolean;
  is_active: boolean;
};

export type TemplateLibraryResponse = {
  entries: TemplateLibraryEntry[];
  active_id: string | null;
};

export type TemplateIssue = {
  code: string;
  message: string;
  blocking: boolean;
};

export type TemplateParagraph = {
  id: number;
  text: string;
  is_bullet: boolean;
  is_heading_candidate: boolean;
  has_tab: boolean;
  has_hyperlink: boolean;
  run_count: number;
  preview: string;
};

export type TemplateSection = {
  key: string;
  heading_paragraph_id: number;
  heading_text: string;
  body_start: number;
  body_end: number;
  entry_count: number;
  bullet_count: number;
  confidence: number;
  aliases_matched: string;
};

export type TemplateAnalyzeResponse = {
  source_sha256: string;
  paragraphs: TemplateParagraph[];
  sections: TemplateSection[];
  suggested_profile: Record<string, unknown> | null;
  issues: TemplateIssue[];
  ready: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  /** JSON fetch that surfaces FastAPI error bodies as thrown Errors. */
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function fetchConfig(): Promise<AppConfig> {
  /** Load UI defaults and the master resume's tag vocabulary. */
  return request<AppConfig>("/api/config");
}

export function fetchResumeOutline(): Promise<ResumeOutline> {
  /** Load the master-resume shape the include tile needs — refetched on every mount
   * so an edit made on the Master resume tab shows up the next time Tailor is visited. */
  return request<ResumeOutline>("/api/resume-outline");
}

export function fetchSettings(): Promise<SettingsResponse> {
  /** Load the active profile's saved run defaults. */
  return request<SettingsResponse>("/api/settings");
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
  return request<WorkspaceActivateResponse>(
    `/api/workspaces/${encodeURIComponent(id)}/activate`,
    { method: "POST" },
  );
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

export function createJob(
  jdText: string,
  settings: JobSettings,
): Promise<{ job_id: string; queue_position: number }> {
  /** Enqueue a tailoring run; returns immediately. */
  return request("/api/jobs", {
    method: "POST",
    body: JSON.stringify({ jd_text: jdText, settings }),
  });
}

export function fetchJob(jobId: string): Promise<JobStatus> {
  /** Poll current job state and accumulated events. */
  return request<JobStatus>(`/api/jobs/${jobId}`);
}

export function fetchMasterResume(): Promise<Record<string, unknown>> {
  /** Load the master resume for the editor. */
  return request("/api/master-resume");
}

export function saveMasterResume(body: Record<string, unknown>): Promise<ValidateResponse> {
  /** Validate and persist the master resume (with a backup of the previous file). */
  return request("/api/master-resume", { method: "PUT", body: JSON.stringify(body) });
}

export function validateMasterResume(body: Record<string, unknown>): Promise<ValidateResponse> {
  /** Dry-run validation without writing. */
  return request("/api/master-resume/validate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function previewUrl(jobId: string): string {
  /** URL of the inline PDF for a finished job. */
  return `/api/jobs/${jobId}/preview.pdf`;
}

export function downloadPdfUrl(jobId: string): string {
  /** URL that forces a PDF Save As (attachment disposition). */
  return `/api/jobs/${jobId}/download.pdf`;
}

export function downloadUrl(jobId: string): string {
  /** URL of the tailored .docx for a finished job. */
  return `/api/jobs/${jobId}/download.docx`;
}

/**
 * Trigger a one-shot browser download of the tailored PDF.
 *
 * Fetches as a blob first so a missing PDF (conversion failed) is a silent no-op
 * instead of navigating the tab to a JSON 404.
 */
export async function triggerPdfDownload(jobId: string): Promise<void> {
  const res = await fetch(downloadPdfUrl(jobId));
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const match = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(
    res.headers.get("Content-Disposition") ?? "",
  );
  const filename = match
    ? decodeURIComponent(match[1].replace(/["']/g, ""))
    : "resume.pdf";
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function expansionUrl(jobId: string): string {
  /** URL of the plain-text expansion for a finished job. */
  return `/api/jobs/${jobId}/expansion.md`;
}

export function fetchTemplateInfo(): Promise<TemplateInfo> {
  /** Load baseline/tagged metadata and calibration freshness for the Template tab. */
  return request<TemplateInfo>("/api/template");
}

export function templatePreviewUrl(): string {
  /** URL of the inline PDF for the tagged template filled with the master resume. */
  return "/api/template/preview.pdf";
}

/**
 * Parse a FastAPI error body from a template upload/analyze response.
 */
async function templateErrorDetail(res: Response): Promise<string> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") {
      detail = d;
    } else if (d && typeof d === "object" && "message" in d) {
      const msg = String((d as { message: string }).message);
      const log = String((d as { log?: string }).log ?? "");
      detail = log ? `${msg}\n\n${log}` : msg;
    } else {
      detail = JSON.stringify(d ?? body);
    }
  } catch {
    /* keep statusText */
  }
  return detail;
}

/**
 * Analyze an uploaded baseline without writing under templates/.
 */
export async function analyzeTemplate(file: File): Promise<TemplateAnalyzeResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/template/analyze", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  return res.json() as Promise<TemplateAnalyzeResponse>;
}

/**
 * Upload a baseline export and rebuild the tagged template.
 *
 * When `profile` is provided it is sent as a multipart JSON field so the server can
 * run the span-aware builder. Omit it for the legacy hard-coded heading path.
 *
 * Uses a bare fetch with FormData — do not set Content-Type, or the browser cannot
 * attach the multipart boundary that FastAPI/python-multipart expects.
 */
export async function uploadTemplate(
  file: File,
  profile?: Record<string, unknown> | null,
  options?: { calibrate?: boolean; label?: string },
): Promise<TemplateBuildResponse> {
  const form = new FormData();
  form.append("file", file);
  if (profile) {
    form.append("profile", JSON.stringify(profile));
  }
  if (options?.calibrate) {
    form.append("calibrate", "true");
  }
  if (options?.label) {
    form.append("label", options.label);
  }
  const res = await fetch("/api/template", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  return res.json() as Promise<TemplateBuildResponse>;
}

/**
 * List named template library entries (seeds Default from live when empty).
 */
export function fetchTemplateLibrary(): Promise<TemplateLibraryResponse> {
  return request<TemplateLibraryResponse>("/api/template/library");
}

/**
 * Activate a library snapshot into the live template slot.
 */
export async function activateTemplateLibrary(
  entryId: string,
  options?: { calibrate?: boolean },
): Promise<TemplateBuildResponse> {
  const qs = options?.calibrate ? "?calibrate=true" : "";
  const res = await fetch(`/api/template/library/${encodeURIComponent(entryId)}/activate${qs}`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  return res.json() as Promise<TemplateBuildResponse>;
}

/**
 * Rename a saved template library entry.
 */
export function renameTemplateLibrary(
  entryId: string,
  label: string,
): Promise<TemplateLibraryResponse> {
  return request<TemplateLibraryResponse>(
    `/api/template/library/${encodeURIComponent(entryId)}`,
    { method: "PATCH", body: JSON.stringify({ label }) },
  );
}

/**
 * Delete a non-active library entry.
 */
export function deleteTemplateLibrary(
  entryId: string,
): Promise<TemplateLibraryResponse> {
  return request<TemplateLibraryResponse>(
    `/api/template/library/${encodeURIComponent(entryId)}`,
    { method: "DELETE" },
  );
}
