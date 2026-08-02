/** Shared types and fetch helpers for the ResumeTailor API. */

export type JobSettings = {
  pages: number;
  experience: number | null;
  projects: number | null;
  model: string;
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

export type RunReport = {
  title: string;
  seniority: string;
  coverage_matched: number;
  coverage_total: number;
  missing_must_haves: string[];
  unmatched_canonicals: string[][];
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
  effort_options: string[];
  pdf_backend: string;
  calibration_source: string;
  chars_per_line: number;
  lines_per_page: number;
  tag_vocabulary: string[];
  contact_name: string | null;
  fill_target: number;
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

export type TemplateInfo = {
  baseline: TemplateFileInfo;
  tagged: TemplateFileInfo;
  experience_entries: number;
  project_entries: number;
  bullets: number;
  calibration: CalibrationInfo;
  preview_available: boolean;
};

export type TemplateBuildResponse = {
  ok: boolean;
  log: string;
  info: TemplateInfo | null;
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
 * Upload a Google Docs export, replace the baseline, and rebuild the tagged template.
 *
 * Uses a bare fetch with FormData — do not set Content-Type, or the browser cannot
 * attach the multipart boundary that FastAPI/python-multipart expects.
 */
export async function uploadTemplate(file: File): Promise<TemplateBuildResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/template", { method: "POST", body: form });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      const d = body.detail;
      if (typeof d === "string") {
        detail = d;
      } else if (d && typeof d === "object" && "message" in d) {
        // Build failures return { message, log }; surface both for the Template tab.
        const msg = String((d as { message: string }).message);
        const log = String((d as { log?: string }).log ?? "");
        detail = log ? `${msg}\n\n${log}` : msg;
      } else {
        detail = JSON.stringify(d ?? body);
      }
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<TemplateBuildResponse>;
}
