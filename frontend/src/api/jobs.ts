/** Tailoring runs: job settings, progress and reports, run history, artifacts, re-render. */

import type { ApplySettings } from "./applySettings";
import { apiError, request } from "./core";

export type ContactField = "location" | "email" | "phone" | "linkedin" | "github";

export type IncludeOptions = {
  /** Ordered contact-line fields, name excluded (it always renders first). Omitting a
   * field both hides it and shortens the line. Null keeps the active template's order. */
  contact_fields: ContactField[] | null;
  gpa: boolean;
  coursework: boolean;
  /** Entry ids (any experience/project section) omitted from this run entirely — one
   * flat namespace, matching the server's `IncludeOptions.exclude_entries`. */
  exclude_entries: string[];
  /** Whole section ids omitted from this run entirely. */
  exclude_sections: string[];
  /** Legacy: folded into the same exclusion set as `exclude_entries` server-side. Kept
   * only so a `settings.json` saved before `exclude_entries` existed still round-trips. */
  exclude_experience: string[];
  exclude_projects: string[];
  /** Per-run display order for resume sections, by id. Null keeps the resume's own
   * order. Sections not named here keep their relative position and are appended after
   * the named ones. Has no visible effect under a `"fixed"` template — see
   * `ResumeOutline.section_mode`. */
  section_order: string[] | null;
};

export type CoverAngles = {
  why_company: string;
  problem: string;
  approach: string;
  tone: "" | "formal" | "direct" | "conversational" | "mirror";
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
  skills_model: string | null;
  cover_model: string | null;
  /** Override for the opt-in hiring-manager review stage (CLI `--review` today). */
  review_model: string | null;
  /** Override for application-form free-text answers (`apply.answer`). */
  answer_model: string | null;
  effort: "low" | "medium" | "high" | null;
  no_semantic: boolean;
  no_widow_repair: boolean;
  no_verb_repair: boolean;
  /** Combine near-duplicate bullets within an entry; only fires if the page overflows. */
  merge: boolean;
  no_cache: boolean;
  /** JD extraction votes (0-10); 0 = automatic (1 on Anthropic/Gemini, 3 on local
   * models). Set on Settings → Models. */
  extract_runs: number;
  max_concurrent_jobs: number;
  /** Skip generating expanded experience descriptions for application forms. */
  no_expand: boolean;
  /** Skip generating the tailored skills list for application-form Skills fields. */
  no_skills: boolean;
  /** Generate a cover letter after the tailored resume succeeds. */
  cover_letter: boolean;
  no_cover_letter: boolean;
  /** Optional cover-letter angle inputs (why company / problem / approach / tone). */
  cover_angles: CoverAngles;
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
  /** After a successful run, draft vocabulary-library proposals from its own
   * near-miss keyword gaps and unclassified opening verbs, using the run's own
   * backend — unlike the Settings tab's manual "Generate suggestions" button, which
   * runs outside any job and so falls back to Claude on a fresh server with no
   * Anthropic key, regardless of the saved Model setting. */
  suggest_vocabulary: boolean;
  /** Editable style block for resume bullet rewriting; null uses the shipped default. */
  rewrite_style: string | null;
  /** Editable style block for application-form expansion; null uses the shipped default. */
  expand_style: string | null;
  /** Editable style block for cover-letter drafting; null uses the shipped default. */
  cover_style: string | null;
  /** One blanket model override applied to every stage of the selected profile. */
  model_name: string | null;
  /** Daily discover/screen/fill funnel settings. */
  apply: ApplySettings;
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
  /** Score-neutral posting weight from JD extraction. */
  band?: string;
  /** Where the band came from (`stated` / `structural` / `inferred`). */
  evidence_tier?: string;
};

export type RunReport = {
  quality?: import("../lib/resumeQuality").ResumeQuality | null;
  title: string;
  seniority: string;
  coverage_matched: number;
  coverage_total: number;
  missing_must_haves: string[];
  unmatched_canonicals: string[][];
  gaps: KeywordGap[];
  /** Why coverage is unmeasurable; null/absent when the ratio is real. */
  extraction_diagnosis?: string | null;
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
  /** Non-null only when a calibration file existed but was rejected as implausible. */
  calibration_rejection: string | null;
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

export type SkillSuggestion = {
  skill: string;
  pool_label: string;
  tier: "required" | "preferred" | "additional";
  jd_phrase: string;
  sources: string[];
  reason: string;
};

export type SkillsPlan = {
  skills: SkillSuggestion[];
  warnings: string[];
  model: string;
  pool_size: number;
};

export type CoverLetter = {
  company: string;
  company_location: string;
  addressee: string;
  paragraphs: string[];
  salutation: string;
  closing: string;
  signature: string;
  inside_address: string[];
  date: string;
  warnings: string[];
  model: string;
  word_count: number;
  has_docx: boolean;
  has_pdf: boolean;
};

export type JobStatus = {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  queue_position: number | null;
  error: string | null;
  report: RunReport | null;
  expansion: Expansion | null;
  skills: SkillsPlan | null;
  cover_letter: CoverLetter | null;
  events: ProgressEvent[];
  created_at?: string | null;
  title?: string | null;
};

/** One row from `GET /api/jobs` — recent-runs list for the Tailor tab. */
export type RunHistoryEntry = {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  created_at: string;
  finished_at: string | null;
  title: string;
  /** From the posting's metadata when known (apply funnel, JD from a link); "" otherwise. */
  company?: string;
  error: string | null;
  pages: number | null;
  coverage_matched: number | null;
  coverage_total: number | null;
  has_pdf: boolean;
  has_docx: boolean;
};

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

export interface RunEstimate {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  /** Null when a stage's model has no known price (never guessed). */
  usd: number | null;
  /** Every stage runs on a local model: nothing to pay. */
  local: boolean;
  /** How the run is paid for: dollars per token, free on this machine, or an Ollama
   * Cloud plan. Absent from servers older than the field. */
  billing?: "per_token" | "local" | "subscription";
  stages: {
    stage: string;
    model: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    usd: number | null;
    billing?: "per_token" | "local" | "subscription";
  }[];
}

export function estimateJob(jdText: string, settings: JobSettings): Promise<RunEstimate> {
  /** Estimated calls, tokens and cost of a run; no model call is made. */
  return request("/api/jobs/estimate", {
    method: "POST",
    body: JSON.stringify({ jd_text: jdText, settings }),
  });
}

export function fetchJob(jobId: string): Promise<JobStatus> {
  /** Poll current job state and accumulated events. */
  return request<JobStatus>(`/api/jobs/${jobId}`);
}

/**
 * Newest-first recent runs for the active profile (disk + in-memory overlay).
 */
export function fetchRunHistory(): Promise<RunHistoryEntry[]> {
  return request<{ runs: RunHistoryEntry[] }>("/api/jobs").then((r) => r.runs);
}

export function cancelJob(jobId: string): Promise<JobStatus> {
  /** Cancel a queued or running job. A queued job stops immediately; a running one
   * stops cooperatively at its next pipeline-stage checkpoint. */
  return request<JobStatus>(`/api/jobs/${jobId}`, { method: "DELETE" });
}

export type DeleteRunHistoryResult = {
  deleted: string[];
  errors: Record<string, string>;
};

export function deleteRunHistory(jobIds: string[]): Promise<DeleteRunHistoryResult> {
  /** Remove finished runs from disk-backed history for the active profile. */
  return request<DeleteRunHistoryResult>("/api/jobs/history/delete", {
    method: "POST",
    body: JSON.stringify({ job_ids: jobIds }),
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
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(
    res.headers.get("Content-Disposition") ?? "",
  );
  const filename = match ? decodeURIComponent(match[1].replace(/["']/g, "")) : "resume.pdf";
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

export function skillsUrl(jobId: string): string {
  /** URL of the plain-text tailored skills list for a finished job. */
  return `/api/jobs/${jobId}/skills.md`;
}

export function recordSkillsCopy(jobId: string): Promise<void> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/artifact-usage`, {
    method: "POST",
    body: JSON.stringify({ artifact: "skills", action: "copy" }),
  });
}

export function coverLetterMdUrl(jobId: string): string {
  return `/api/jobs/${jobId}/cover-letter.md`;
}

export function coverLetterDocxUrl(jobId: string): string {
  return `/api/jobs/${jobId}/cover-letter.docx`;
}

export function coverLetterPdfUrl(jobId: string): string {
  return `/api/jobs/${jobId}/cover-letter.pdf`;
}

export function coverLetterPreviewUrl(jobId: string, cacheBuster?: number): string {
  /** Inline cover-letter PDF for the results card; optional ``?v=`` busts regenerate cache. */
  const base = `/api/jobs/${jobId}/cover-letter/preview.pdf`;
  return cacheBuster === undefined ? base : `${base}?v=${cacheBuster}`;
}

/** Write a finished run's application-form experience text on demand (one model call). */
export function generateExpansion(jobId: string): Promise<Expansion> {
  return request<Expansion>(`/api/jobs/${jobId}/expansion`, { method: "POST" });
}

export function regenerateCoverLetter(jobId: string, instruction: string): Promise<CoverLetter> {
  return request<CoverLetter>(`/api/jobs/${jobId}/cover-letter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  });
}

export interface JdText {
  text: string;
  source: string;
  ats: string;
  final_url: string;
  warnings: string[];
}

/** Read a posting's text from its URL (resolves job-board redirect links). */
export function fetchJdFromUrl(url: string): Promise<JdText> {
  return request("/api/jd/fetch", { method: "POST", body: JSON.stringify({ url }) });
}

/** Extract posting text from an uploaded .txt / .pdf / .docx / .html file. */
export async function extractJdFile(file: File): Promise<JdText> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/jd/extract-file", { method: "POST", body: form });
  if (!res.ok) throw await apiError(res);
  return res.json() as Promise<JdText>;
}

export interface JobBullet {
  bullet_id: string;
  section_title: string;
  entry_label: string;
  /** The master resume's text (merged bullets: each source joined by " / "). */
  source_text: string;
  ai_text: string;
  /** What the current document shows; null when removed. */
  current_text: string | null;
  merged_from: string[];
}

export interface RerenderRequest {
  edits: Record<string, string>;
  reverted: string[];
  removed: string[];
  confirmed: string[];
}

export type RerenderResult =
  | { status: "needs_confirmation"; flagged: Record<string, string[]> }
  | { status: "over"; pages: number; target_pages: number; over_by_lines: number }
  | {
      status: "saved";
      pages: number;
      pages_are_estimated: boolean;
      warnings: string[];
      flagged: Record<string, string[]>;
    };

export function fetchJobBullets(jobId: string): Promise<{ bullets: JobBullet[] }> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/bullets`);
}

/** Render the edited bullets with the run's template. No AI call. */
export function rerenderJob(jobId: string, body: RerenderRequest): Promise<RerenderResult> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/rerender`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
