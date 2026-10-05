/** Tracked applications: rows, review fields, operations, daily status, extension. */

import type { ApplySettings } from "./applySettings";
import { conditionalGet, request } from "./core";

export type ApplyFieldOutcome = {
  field_id?: string;
  frame_id?: string;
  step_id?: string;
  label?: string;
  canonical_key?: string;
  state?:
    | "verified_filled"
    | "preserved"
    | "unanswered"
    | "ambiguous"
    | "invalid_existing"
    | "manual_review"
    | "failed";
  required?: boolean;
  observed_value?: string;
  answer_source?: string;
  reason_code?: string;
  reason_text?: string;
  // Retained for application records written by the legacy engine.
  value?: string;
  preserved?: boolean;
};

export type ApplyReviewField = {
  field_id: string;
  frame_id?: string;
  document_generation?: string;
  canonical_key?: string;
  label: string;
  control_kind: string;
  current_value: string;
  selection_state?: string;
  enabled?: boolean;
  required: boolean;
  expected_state_hash: string;
  constraints?: {
    maxlength?: number;
    max_length?: number;
    type?: string;
    input_type?: string;
    min?: string;
    max?: string;
  };
  options: Array<{
    option_id: string;
    label: string;
    value?: string;
    enabled: boolean;
    placeholder: boolean;
    selected?: boolean;
  }>;
};

export type ApplyAttachment = {
  purpose?: string;
  filename?: string;
  verified?: boolean;
  error?: string;
  state?:
    | "not_requested"
    | "preserved"
    | "uploading"
    | "verified"
    | "missing_artifact"
    | "rejected"
    | "unverifiable";
  expected_filename?: string;
  observed_filename?: string;
  reason?: string;
};

export type ApplicationRow = {
  resume_review?: {
    quality: import("../lib/resumeQuality").ResumeQuality;
    warnings: string[];
    revision: string;
    acknowledged: boolean;
    required: boolean;
  } | null;
  source_job_id: string;
  company: string;
  role: string;
  location: string;
  posting_url: string;
  final_url: string;
  ats: string;
  status: string;
  status_history?: Array<{ status: string; at: string; note?: string }>;
  status_at?: string;
  discovered_at: string;
  /** Posting date (ISO date); the date found instead when `posted_known` is false. */
  posted_at?: string;
  posted_known?: boolean;
  archived_at?: string | null;
  job_id: string | null;
  preparation_eligible?: boolean;
  preparation_reasons?: string[];
  /** Which retry the server would run (`daily.retry_kind`); null when there is none. */
  retry_kind?: "fetch" | "prefilter" | "tailor" | null;
  /** Short "why screened out" label (`screen.screen_label`); null otherwise. */
  screen_label?: string | null;
  /** What a "Needs your review" row is waiting on (`store.review_summary`). */
  review_summary?: string | null;
  /** LinkedIn/Indeed apply path recorded by the browser extension. */
  apply_kind?: ApplyKind;
  /** Saved from search results by the extension, description not captured yet. */
  capture_stub?: boolean;
  screen: {
    passed: boolean;
    coverage: number;
    coverage_matched: number;
    coverage_total: number;
    reasons: string[];
    flags: string[];
    /** JD sentence behind each work-restriction reason. */
    evidence?: string[];
    seniority?: string;
  } | null;
  error: string | null;
  notes: string;
  sources: string[];
  group_size: number;
  salary: string;
  eligibility_flags: string[];
  duplicate_of: string | null;
  otp_prompt?: string | null;
  fill?: {
    status?: string;
    ready_to_submit?: boolean;
    required_empty?: string[];
    leftovers?: Array<{ label?: string; reason?: string; required?: boolean }>;
    uploads?: ApplyAttachment[];
    error?: string | null;
    browser_target_id?: string;
    browser_url?: string;
    handoff_reason?: string;
    final_step_reached?: boolean;
    field_outcomes?: ApplyFieldOutcome[];
    review_snapshot_id?: string;
    review_fields?: ApplyReviewField[];
    missing_profile?: MissingProfileField[];
    /** Written answers the fill drafted, by question. */
    long_text_answers?: Record<string, string>;
    confirmation?: string;
  } | null;
};

export const acknowledgeApplicationResume = (id: string, revision: string) =>
  request<ApplicationRow>(`/api/applications/${encodeURIComponent(id)}/resume-acknowledgement`, {
    method: "POST",
    body: JSON.stringify({ revision }),
  });

/** Questions a fill recognised as a profile fact the profile leaves blank. */
export type MissingProfileField = {
  key: string;
  field_label: string;
  section: string;
  path: string;
  questions: string[];
  /** Filled anyway this time (a saved answer or the Autofill model). */
  answered: boolean;
};

export type ApplicationsList = {
  applications: ApplicationRow[];
  counts: Record<string, number>;
  total: number;
};

export type InFlightItem = {
  application_id: string;
  label: string;
  job_id: string;
  step: number;
  step_id: string;
  action_label: string;
  field_label: string;
  stage: string;
  started_at: string;
  deadline_at: string;
};

export type AttentionItem = {
  application_id: string;
  label: string;
  kind: "failed" | "needs_input" | "ready_for_review" | "blocked";
  message: string;
  at: string;
};

export type ApplyOperation = {
  operation_id: string;
  action: "find" | "prepare" | "fill" | "inspect" | "correct";
  state: string;
  application_ids: string[];
  in_flight?: InFlightItem[];
  current_application_id: string;
  /** The tailor job of the item Prepare is working on, while it runs; "" otherwise. */
  current_job_id?: string;
  current_label: string;
  stage: string;
  message: string;
  processed: number;
  total: number;
  completed: number;
  find_progress?: {
    phase: "discovering" | "processing";
    processed: number;
    total: number;
    current: string;
  } | null;
  blocked: number;
  failed: number;
  submitted: number;
  started_at: string;
  updated_at: string;
  heartbeat_at: string;
  current_step: number;
  current_step_id?: string;
  current_step_number?: number;
  current_action_id?: string;
  current_action_label?: string;
  current_field_label?: string;
  action_started_at?: string;
  last_activity_at?: string;
  application_started_at: string;
  application_deadline_at?: string;
  ready_for_review?: number;
  needs_input?: number;
  attention?: AttentionItem[];
  finished_at: string;
  effective_model: string;
  auto_submit: boolean;
  blocker_mode: "pause" | "continue";
  events: Array<{ at?: string; stage?: string; message?: string; application_id?: string }>;
  excluded?: Record<string, string[]>;
};

export function startApplyOperation(options: {
  action: "find" | "prepare" | "fill";
  fill_mode?: "initial" | "continue" | "reopen";
  force_prepare?: boolean;
  application_ids?: string[];
  limit?: number | null;
  /** One-off posting-age window for Find; null uses the saved setting. */
  max_age_days?: number | null;
  dry_run?: boolean;
  auto_submit: boolean;
  blocker_mode: "pause" | "continue";
  model_provider: ApplySettings["model_provider"];
  model_name: string;
}): Promise<ApplyOperation> {
  return request("/api/applications/operations", {
    method: "POST",
    body: JSON.stringify({
      ...options,
      application_ids: options.application_ids ?? [],
      limit: options.limit ?? null,
      max_age_days: options.max_age_days ?? null,
      dry_run: options.dry_run ?? false,
    }),
  });
}

export function listApplyOperations(): Promise<ApplyOperation[]> {
  return request("/api/applications/operations");
}

export function getApplyOperation(operationId: string): Promise<ApplyOperation> {
  return request(`/api/applications/operations/${encodeURIComponent(operationId)}`);
}

export function focusApplicationReviewTab(sourceJobId: string): Promise<{ url: string }> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}/review-tab`, {
    method: "POST",
  });
}

export function refreshApplicationReview(sourceJobId: string): Promise<ApplyOperation> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}/review/refresh`, {
    method: "POST",
  });
}

export function correctApplicationField(
  sourceJobId: string,
  body: {
    snapshot_id: string;
    field_id: string;
    expected_state_hash: string;
    value?: string | null;
    option_ids?: string[];
    idempotency_key: string;
  },
): Promise<ApplyOperation> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}/corrections`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function controlApplyOperation(
  operationId: string,
  action: "pause" | "resume" | "skip" | "cancel",
): Promise<ApplyOperation> {
  return request(`/api/applications/operations/${encodeURIComponent(operationId)}/control`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export type BrowserStatus = {
  reachable: boolean;
  browser: string;
  user_agent: string;
  error: string;
  cdp_url: string;
};

export type Packet = {
  job_id: string;
  company: string;
  role: string;
  ats: string;
  posting_url: string;
  fields: Record<string, string>;
  education: Array<Record<string, string>>;
  experience: Array<Record<string, unknown>>;
  skills: string[];
  cover_letter: string;
  artifacts: Record<string, string>;
  gaps: Array<Record<string, unknown>>;
};

export type ApplicationListOptions = {
  status?: string;
  q?: string;
  archive?: "active" | "archived" | "all";
  /** "review" = rows waiting on the applicant; "working" = everything else. */
  group?: "review" | "working";
  sort?: string;
  direction?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

/** List tracked applications with server-side search, sort, and pagination. */
export function listApplications(options: ApplicationListOptions = {}): Promise<ApplicationsList> {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  if (options.q) params.set("q", options.q);
  if (options.archive) params.set("archive", options.archive);
  if (options.group) params.set("group", options.group);
  if (options.sort) params.set("sort", options.sort);
  if (options.direction) params.set("direction", options.direction);
  params.set("limit", String(options.limit ?? 25));
  params.set("offset", String(options.offset ?? 0));
  return conditionalGet(`/api/applications?${params}`);
}

export function archiveApplications(
  applicationIds: string[],
  archived: boolean,
): Promise<{ updated: string[]; errors: Record<string, string> }> {
  return request("/api/applications/archive", {
    method: "POST",
    body: JSON.stringify({ application_ids: applicationIds, archived }),
  });
}

export function undoSubmitted(sourceJobId: string): Promise<ApplicationRow> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}/undo-submitted`, {
    method: "POST",
  });
}

/** Load one application plus packet and JD when available. */
export function getApplication(sourceJobId: string): Promise<{
  application: ApplicationRow;
  packet: Packet | null;
  jd_text: string | null;
}> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}`);
}

/** Update an application's funnel status. */
export function setApplicationStatus(
  sourceJobId: string,
  status: string,
  note = "",
): Promise<ApplicationRow> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}/status`, {
    method: "POST",
    body: JSON.stringify({ status, note }),
  });
}

/** Re-run the failed step for one application (fetch JD, re-check the eligibility
 * prefilter, or re-queue tailoring). A tailor retry returns as soon as it is queued. */
export function retryApplication(sourceJobId: string): Promise<ApplicationRow> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}/retry`, {
    method: "POST",
  });
}

/** Live progress of the in-flight (or last finished) daily pass. */
export type DailyStatus = {
  running: boolean;
  phase: string;
  source_id: string;
  current: string;
  processed: number;
  total: number;
  dry_run: boolean;
  fetch_only?: boolean;
  started_at: string;
  finished_at: string;
  date: string;
  summary: (Record<string, unknown> & { attention?: AttentionItem[] }) | null;
  scheduler?: SchedulerStatus | null;
};

/** When the nightly pass last ran and will run next (`apply/scheduler.py`). */
export type SchedulerStatus = {
  enabled: boolean;
  schedule_time: string;
  last_run_date: string | null;
  last_started_at: string | null;
  next_run_at: string | null;
  missed_today: boolean;
  last_error: string | null;
};

/** Poll phase/counters for the daily funnel. */
export function getDailyStatus(): Promise<DailyStatus> {
  return request("/api/applications/daily-status");
}

/** Save the applicant's own notes on one application. */
export function setApplicationNotes(sourceJobId: string, notes: string): Promise<ApplicationRow> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}/notes`, {
    method: "PUT",
    body: JSON.stringify({ notes }),
  });
}

/** Start the nightly pass now; 409 while another Apply task runs. */
export function runDailyNow(): Promise<DailyStatus> {
  return request("/api/applications/daily-run", { method: "POST" });
}

/** Probe host browser CDP reachability (Edge recommended — see README). */
export function getBrowserStatus(): Promise<BrowserStatus> {
  return request("/api/browser/status");
}

export type ExtensionPairing = {
  id: string;
  label: string;
  created_at: string;
  last_seen: string;
};

export function createExtensionPairingCode(): Promise<{ code: string; expires_in: number }> {
  return request("/api/extension-pairings/code", { method: "POST" });
}

export function listExtensionPairings(): Promise<ExtensionPairing[]> {
  return request("/api/extension-pairings");
}

export function revokeExtensionPairing(id: string): Promise<void> {
  return request(`/api/extension-pairings/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** How a LinkedIn/Indeed job is applied to (`store.ApplyKind`). */
export type ApplyKind = "easy_apply" | "external" | "unknown";

/** A row the browser extension captured (`GET /api/extension-captures`). */
export type CapturedItem = {
  id: string;
  /** Colon-free id for `/applications/<id>` links (the row's source id). */
  link_id: string;
  company: string;
  role: string;
  location: string;
  status: string;
  /** "linkedin" / "indeed" for board jobs, else the ATS. */
  site: string;
  posting_url: string;
  /** Saved from search results without its description ("Needs description"). */
  capture_stub: boolean;
  apply_kind: ApplyKind;
  discovered_at: string;
};

export function listExtensionCaptures(stubsOnly = false): Promise<CapturedItem[]> {
  return request(`/api/extension-captures${stubsOnly ? "?stubs_only=true" : ""}`);
}

/** Open browser tab ids; `reachable: false` means tab state is unknown. */
export function getOpenTabs(): Promise<{ reachable: boolean; target_ids: string[] }> {
  return request("/api/applications/open-tabs");
}

/** CSV download URL for the applications tracker export. */
export function applicationsExportUrl(): string {
  return "/api/applications/export.csv";
}

/** A guarded draft for one free-text application question (`POST /api/jobs/{id}/answer`). */
export type AnswerDraft = {
  answer: string;
  offenders: string[];
  warnings: string[];
  source: string;
  model: string;
};

/** Draft an answer from the whole resume, safe profile facts and the typed `context`. */
export function answerApplicationQuestion(
  jobId: string,
  body: { question: string; context: string; maxChars: number; regenerate?: boolean },
): Promise<AnswerDraft> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/answer`, {
    method: "POST",
    body: JSON.stringify({
      question: body.question,
      context: body.context,
      max_chars: body.maxChars,
      full_resume: true,
      regenerate: body.regenerate ?? false,
    }),
  });
}
