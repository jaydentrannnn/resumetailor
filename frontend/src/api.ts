/** Shared types and fetch helpers for the ResumeTailor API. */

export type JobSettings = {
  pages: number;
  experience: number | null;
  projects: number | null;
  model: string;
  rewrite_model: string | null;
  effort: "low" | "medium" | "high" | null;
  no_semantic: boolean;
  no_widow_repair: boolean;
  no_verb_repair: boolean;
  /** Combine near-duplicate bullets within an entry; only fires if the page overflows. */
  merge: boolean;
  no_cache: boolean;
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

export type JobStatus = {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  queue_position: number | null;
  error: string | null;
  report: RunReport | null;
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
};

export type ValidateResponse = {
  ok: boolean;
  errors: string[];
  summary: Record<string, unknown> | null;
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

export function downloadUrl(jobId: string): string {
  /** URL of the tailored .docx for a finished job. */
  return `/api/jobs/${jobId}/download.docx`;
}
