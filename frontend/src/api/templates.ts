/** Resume templates: info, analysis, previews, upload, library, calibration, defaults. */

import { request, templateErrorDetail } from "./core";

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
  /** When page fit was last tuned for this PDF engine (ISO); null when never. */
  calibrated_at?: string | null;
};

export type CalibrateResult = {
  ok: boolean;
  log: string;
  warnings: string[];
  calibration: CalibrationInfo;
};

export function calibrateTemplate(): Promise<CalibrateResult> {
  /** Measure page-fit constants for the active template (takes a few seconds). */
  return request<CalibrateResult>("/api/template/calibrate", { method: "POST" });
}

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

export type TemplateFieldCandidate = {
  field: string;
  paragraph_id: number;
  start: number;
  end: number;
  confidence: number;
  preview: string;
  section_heading_paragraph_id: number | null;
};

export type TemplateAnalyzeResponse = {
  source_sha256: string;
  paragraphs: TemplateParagraph[];
  sections: TemplateSection[];
  field_candidates: TemplateFieldCandidate[];
  suggested_profile: Record<string, unknown> | null;
  issues: TemplateIssue[];
  ready: boolean;
};

/** A heading kind the wizard's remap step can assign, or `null` for "not a section". */
export type TemplateHeadingKind =
  "experience" | "education" | "projects" | "skills" | "list" | null;

export function fetchTemplateInfo(): Promise<TemplateInfo> {
  /** Load baseline/tagged metadata and calibration freshness for the Template tab. */
  return request<TemplateInfo>("/api/template");
}

export function templatePreviewUrl(): string {
  /** URL of the inline PDF for the tagged template filled with the master resume. */
  return "/api/template/preview.pdf";
}

/**
 * Analyze an uploaded baseline without writing under templates/.
 */
export async function analyzeTemplate(
  file: File,
  options?: { convertBullets?: boolean },
): Promise<TemplateAnalyzeResponse> {
  const form = new FormData();
  form.append("file", file);
  if (options?.convertBullets) {
    form.append("convert_bullets", "true");
  }
  const res = await fetch("/api/template/analyze", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  return res.json() as Promise<TemplateAnalyzeResponse>;
}

/**
 * Re-analyze a previously uploaded baseline with specific headings' kinds forced by
 * the user. `overrides` maps a heading paragraph id to a confirmed kind, or `null` to
 * say "this is not a section" — a real server round trip, since reassigning one
 * heading can change entry splitting, field reconciliation, and date detection for
 * the rest of the document, not just that one row.
 */
export async function remapTemplateHeadings(
  sourceSha256: string,
  overrides: Record<number, TemplateHeadingKind>,
): Promise<TemplateAnalyzeResponse> {
  return request<TemplateAnalyzeResponse>("/api/template/analyze/remap", {
    method: "POST",
    body: JSON.stringify({ source_sha256: sourceSha256, overrides }),
  });
}

/**
 * Fetch a PDF of the uploaded (not-yet-installed) baseline, for the wizard's
 * side-by-side comparison. Returns an object URL the caller must revoke when done.
 */
export async function fetchTemplateSourcePreview(sourceSha256: string): Promise<string> {
  const res = await fetch("/api/template/preview/source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_sha256: sourceSha256, overrides: {} }),
  });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/**
 * Fetch a PDF of the master resume rendered through a staged (not-yet-installed)
 * profile — what installing this exact mapping would produce. Returns an object URL
 * the caller must revoke when done.
 */
export async function fetchTemplateDraftPreview(
  sourceSha256: string,
  profile: Record<string, unknown>,
): Promise<string> {
  const res = await fetch("/api/template/preview/draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_sha256: sourceSha256, profile }),
  });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/**
 * Upload a baseline export and rebuild the tagged template.
 *
 * `profile` is required — the server has no hard-coded-heading fallback (retired
 * along with the rest of the legacy build path); confirm one via `analyzeTemplate`
 * (and optionally `remapTemplateHeadings`) first.
 *
 * Uses a bare fetch with FormData — do not set Content-Type, or the browser cannot
 * attach the multipart boundary that FastAPI/python-multipart expects.
 */
export async function uploadTemplate(
  file: File,
  profile: Record<string, unknown>,
  options?: { calibrate?: boolean; label?: string; convertBullets?: boolean },
): Promise<TemplateBuildResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("profile", JSON.stringify(profile));
  if (options?.convertBullets) {
    form.append("convert_bullets", "true");
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

/** One built-in starter template (`GET /api/template/defaults`). */
export type DefaultTemplate = {
  name: string;
  label: string;
  description: string;
  /** The design lists Education first; offer to reorder the resume to match. */
  education_first: boolean;
  /** Its saved library entry, when it has been installed before. */
  library_id: string | null;
  is_active: boolean;
};

export async function fetchDefaultTemplates(): Promise<DefaultTemplate[]> {
  const body = await request<{ templates: DefaultTemplate[] }>("/api/template/defaults");
  return body.templates;
}

/** Make a starter template the active one (built and installed like an upload). */
export async function installDefaultTemplate(
  name: string,
  options?: { calibrate?: boolean },
): Promise<TemplateBuildResponse> {
  const qs = options?.calibrate ? "?calibrate=true" : "";
  const res = await fetch(`/api/template/defaults/${encodeURIComponent(name)}/install${qs}`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  return res.json() as Promise<TemplateBuildResponse>;
}

export function defaultTemplateThumbUrl(name: string): string {
  return `/api/template/defaults/${encodeURIComponent(name)}/thumb.png`;
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
  return request<TemplateLibraryResponse>(`/api/template/library/${encodeURIComponent(entryId)}`, {
    method: "PATCH",
    body: JSON.stringify({ label }),
  });
}

/**
 * Delete a non-active library entry.
 */
export function deleteTemplateLibrary(entryId: string): Promise<TemplateLibraryResponse> {
  return request<TemplateLibraryResponse>(`/api/template/library/${encodeURIComponent(entryId)}`, {
    method: "DELETE",
  });
}
