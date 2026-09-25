/** Shared types and fetch helpers for the ResumeTailor API. */

import { ApiError } from "./lib/errors";

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

export type ScreenSettings = {
  allowed_seniority: string[];
  block_patterns: string[];
};

export type SourceConfig = {
  id: string;
  kind: "simplify_html" | "pipe_table";
  url: string;
  categories: string[];
  enabled: boolean;
};

export type EligibilitySettings = {
  hard_reject_years: number;
  flag_years: number;
  extra_title_block: string[];
  extra_text_block: string[];
};

export type ApplySettings = {
  enabled: boolean;
  schedule_time: string;
  readme_url: string;
  categories: string[];
  sources: SourceConfig[];
  max_age_days: number;
  exclude_advanced_degree: boolean;
  exclude_citizenship_required: boolean;
  exclude_no_sponsorship: boolean;
  max_new_per_day: number;
  screen: ScreenSettings;
  eligibility: EligibilitySettings;
  auto_submit_ats: string[];
  auto_submit_max_per_run: number;
  /** Rolling 24-hour caps on automatic submits; 0 means none. */
  auto_submit_max_per_day: number;
  auto_submit_max_per_company_per_day: number;
  auto_submit_enabled: boolean;
  blocker_mode: "pause" | "continue";
  reuse_threshold: number;
  cover_letter: boolean;
  // Provider + model for the funnel's own extract/answer calls — separate from the
  // Tailor model setting. See `ApplySettings.model_spec` on the backend.
  model_provider: "ollama" | "lmstudio" | "gemini" | "anthropic";
  model_name: string;
};

export type ApplicantProfile = {
  first_name: string;
  middle_name?: string;
  last_name: string;
  preferred_name: string;
  pronouns: string;
  email: string;
  phone: string;
  phone_device_type?: string;
  phone_country_code: string;
  phone_country_region: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  portfolio_only_when_asked: boolean;
  work_authorization: string;
  authorized_to_work?: boolean | null;
  authorization_country?: string;
  requires_sponsorship_now: boolean | null;
  requires_sponsorship_future: boolean | null;
  f1_opt_eligible: boolean | null;
  earliest_start: string;
  notice_period?: string;
  highest_education_obtained: string;
  salary_expectation: string;
  /** Structured range behind salary answers; seeded from `salary_expectation`. */
  salary_hourly_min: number | null;
  salary_hourly_max: number | null;
  salary_yearly_min: number | null;
  salary_yearly_max: number | null;
  willing_to_relocate: boolean | null;
  location_preference: string;
  over_18: boolean | null;
  relatives_at_company: boolean | null;
  referred_by: string;
  how_heard: string;
  workday_email?: string;
  workday_password?: string;
  eeo: {
    gender: string;
    race: string;
    race_detail?: string;
    hispanic_latino?: boolean | null;
    veteran: string;
    disability: string;
  };
  /** Spoken languages (`profile.LanguageEntry`); absent on profiles saved before it existed. */
  languages?: ApplicantLanguage[];
  custom_answers: Record<string, string>;
  /** Sets sponsorship defaults (`profile.sponsorship_from_visa`). */
  visa_status?: VisaStatus;
  /** "YYYY-MM"; overrides the resume's graduation month on forms. */
  graduation_date?: string;
  /** Blank = derived from the graduation date. */
  class_year?: "" | "freshman" | "sophomore" | "junior" | "senior" | "graduate";
  gpa_display?: string;
  /** Server-owned: set only by the transcript upload route. */
  transcript_path?: string;
  security_clearance?: "" | "none" | "eligible" | "secret" | "top_secret";
  drivers_license?: boolean | null;
  hours_per_week_available?: number | null;
  school_email?: string;
};

export type VisaStatus =
  "" | "none" | "f1" | "f1_opt" | "f1_stem_opt" | "f1_cpt" | "h1b" | "h4_ead" | "other";

export type ApplicantLanguage = {
  language: string;
  fluent: boolean;
  levels: Record<string, string>;
};

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
  source_job_id: string;
  company: string;
  role: string;
  location: string;
  posting_url: string;
  final_url: string;
  ats: string;
  status: string;
  status_history?: Array<{ status: string; at: string; note?: string }>;
  discovered_at: string;
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

export type ApplyOperation = {
  operation_id: string;
  action: "find" | "prepare" | "fill" | "inspect" | "correct";
  state: string;
  application_ids: string[];
  current_application_id: string;
  current_label: string;
  stage: string;
  message: string;
  processed: number;
  total: number;
  completed: number;
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

/** One resume section (any kind, any count), as the include tile lists it. */
export type ResumeOutlineSection = {
  id: string;
  title: string;
  kind: string;
  entries: ResumeOutlineEntry[];
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
  /** Every entry section (any kind, any count), in resume order — the general form of
   * `experience`/`projects` above, which group same-kind sections into one flat list. */
  sections: ResumeOutlineSection[];
  /** A template with no Projects section should not offer project checkboxes or the
   * link toggle. */
  sections_enabled: Record<string, boolean>;
  /** `"fixed"` templates bake section order into the tagged XML, so `section_order` has
   * no visible effect until the template is rebuilt in generic mode. */
  section_mode: string;
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

/** A workspace's own additions and removals, layered on top of its enabled packs. */
export type LibraryOverrides = {
  tag_aliases: Record<string, string>;
  tag_aliases_removed: string[];
  /** verb -> family, one family per overridden verb (not a pack's family -> verbs[]). */
  verb_families: Record<string, string>;
  verb_families_removed: string[];
};

/** One pack's summary row for the pack list — no alias/verb bodies. */
export type LibraryPackSummary = {
  id: string;
  label: string;
  description: string;
  builtin: boolean;
  customized: boolean;
  tag_alias_count: number;
  verb_count: number;
  created_at: string;
  updated_at: string;
};

/** One pack's full contents, for the pack editor. */
export type LibraryPack = {
  id: string;
  label: string;
  description: string;
  builtin: boolean;
  customized: boolean;
  tag_aliases: Record<string, string>;
  verb_families: Record<string, string[]>;
  created_at: string;
  updated_at: string;
};

export type LibraryPackDraft = {
  label: string;
  description: string;
  tag_aliases: Record<string, string>;
  verb_families: Record<string, string[]>;
  /** Allow overwriting a target another pack already claims. */
  force?: boolean;
};

/** Summary of the composed table — per-pack contents already sit in `packs`. */
export type LibraryEffective = {
  tag_alias_count: number;
  verb_count: number;
  fingerprint: string;
};

/** One LLM-drafted vocabulary addition awaiting approval. */
export type LibraryProposal = {
  id: string;
  kind: "tag_alias" | "verb_family";
  alias: string | null;
  canonical: string | null;
  verb: string | null;
  family: string | null;
  rationale: string;
  source: "run" | "manual";
  created_at: string;
};

export type LibraryState = {
  packs: LibraryPackSummary[];
  enabled_packs: string[];
  overrides: LibraryOverrides;
  effective: LibraryEffective;
  /** Notes from composition: a missing pack, a cross-pack verb collision, or a
   * dropped alias chain. Never errors. */
  diagnostics: string[];
  proposals: LibraryProposal[];
  /** Set only by generateLibraryProposals when a draft partially failed (e.g. the
   * model was unreachable) — the call still returns 200 with whatever succeeded. */
  warning: string | null;
};

/** What approving one alias would rewrite in the current master resume, if anything. */
export type LibraryAliasImpact = {
  alias: string;
  canonical: string;
  affected_tags: string[];
  affected_bullets: [string, string][];
};

/** The thrown error for a failed response: FastAPI's `detail`, plus `error`/`hint` codes. */
async function apiError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  let code: string | undefined;
  let hint: string | undefined;
  try {
    const body = await res.json();
    detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    code = typeof body.error === "string" ? body.error : undefined;
    hint = typeof body.hint === "string" ? body.hint : undefined;
  } catch {
    /* keep statusText */
  }
  return new ApiError(detail, res.status, code, hint);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  /** JSON fetch that surfaces FastAPI error bodies as thrown Errors. */
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) throw await apiError(res);
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
  stages: {
    stage: string;
    model: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    usd: number | null;
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

export function fetchMasterResume(): Promise<Record<string, unknown>> {
  /** Load the master resume for the editor. */
  return request("/api/master-resume");
}

export type MasterResumeImportResponse = {
  resume: Record<string, unknown>;
  warnings: string[];
  untagged_bullet_count: number;
};

/**
 * Parse an uploaded .docx or PDF into a `MasterResume` draft — content, not just layout.
 * Writes nothing; the caller loads the result as unsaved editor state and saves
 * through `saveMasterResume` when ready. `suggestTags` additionally runs an opt-in LLM
 * pass for whatever the deterministic import left untagged; `useModel` lets the model
 * sort a PDF's lines into sections (every field is checked against the PDF's text).
 */
export async function importMasterResumeContent(
  file: File,
  options?: { suggestTags?: boolean; useModel?: boolean },
): Promise<MasterResumeImportResponse> {
  const form = new FormData();
  form.append("file", file);
  if (options?.suggestTags) {
    form.append("suggest_tags", "true");
  }
  if (options?.useModel) {
    form.append("use_model", "true");
  }
  const res = await fetch("/api/master-resume/import", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await templateErrorDetail(res));
  }
  return res.json() as Promise<MasterResumeImportResponse>;
}

export function saveMasterResume(body: Record<string, unknown>): Promise<ValidateResponse> {
  /** Validate and persist the master resume (with a backup of the previous file). */
  return request("/api/master-resume", { method: "PUT", body: JSON.stringify(body) });
}

export type MasterResumeMergeResponse = {
  resume: Record<string, unknown>;
  updated: string[];
  added: string[];
  added_sections: string[];
  warnings: string[];
  backup: string | null;
};

/**
 * Fold an already-parsed draft (typically `MasterResumeImportResponse.resume`) into
 * the current master resume and save the result — matching entries updated in place,
 * new ones added, everything else left untouched. Unlike `saveMasterResume`, this
 * writes unconditionally (no separate confirm step server-side); the caller is
 * responsible for confirming with the user first.
 */
export function mergeMasterResume(
  resume: Record<string, unknown>,
): Promise<MasterResumeMergeResponse> {
  return request("/api/master-resume/merge", { method: "POST", body: JSON.stringify(resume) });
}

export function validateMasterResume(body: Record<string, unknown>): Promise<ValidateResponse> {
  /** Dry-run validation without writing. */
  return request("/api/master-resume/validate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface ResumeVersion {
  version: number;
  saved_at: string;
  note: string;
  name: string;
  bullets: number;
  sections: number;
  current: boolean;
}

export type TagSuggestion = { tag: string; matched: string };

export function suggestTags(
  text: string,
  tags: string[],
  vocabulary: string[],
): Promise<{ suggestions: TagSuggestion[] }> {
  /** Known skills (resume vocabulary + pack aliases) the text names but the tags lack. */
  return request("/api/master-resume/suggest-tags", {
    method: "POST",
    body: JSON.stringify({ text, tags, vocabulary }),
  });
}

export function listResumeVersions(): Promise<{ versions: ResumeVersion[]; keep: number }> {
  /** Saved master-resume versions, newest first. */
  return request("/api/master-resume/versions");
}

export function restoreResumeVersion(
  version: number,
): Promise<{ resume: Record<string, unknown>; restored: number }> {
  /** Write an earlier version back as the current master resume. */
  return request(`/api/master-resume/restore/${version}`, { method: "POST" });
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

export function testModel(settings: JobSettings): Promise<CheckResult> {
  /** One tiny model call with these settings (a fraction of a cent on paid APIs). */
  return request("/api/models/test", { method: "POST", body: JSON.stringify({ settings }) });
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

export function fetchCacheUsage(): Promise<CacheUsage> {
  return request("/api/cache");
}

export function clearCache(): Promise<{ removed: number; freed: number }> {
  return request("/api/cache", { method: "DELETE" });
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

export function regenerateCoverLetter(jobId: string, instruction: string): Promise<CoverLetter> {
  return request<CoverLetter>(`/api/jobs/${jobId}/cover-letter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  });
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

export function fetchLibraries(): Promise<LibraryState> {
  /** Every pack (built-in and user-authored), the active profile's selection and
   * overrides, and the composed table's summary. */
  return request<LibraryState>("/api/libraries");
}

export function fetchLibraryPack(id: string): Promise<LibraryPack> {
  /** One pack's full contents, for the pack editor. */
  return request<LibraryPack>(`/api/libraries/packs/${encodeURIComponent(id)}`);
}

/**
 * Parse a `{message, errors}` validation-error body from a pack write, joining every
 * message rather than showing only the first — mirrors `templateErrorDetail`.
 *
 * `message` is itself `"; ".join(errors)` (`LibraryValidationError.__init__`,
 * libraries.py) — a summary derived from `errors`, not a distinct piece of information.
 * Appending `errors.join("\n")` after it would print the same text twice (obviously so
 * when there's exactly one error); `errors` alone is the complete, better-formatted
 * version, so it wins whenever present.
 */
async function libraryErrorDetail(res: Response): Promise<string> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") {
      detail = d;
    } else if (d && typeof d === "object" && "message" in d) {
      const errors = (d as { errors?: string[] }).errors ?? [];
      detail = errors.length ? errors.join("\n") : String((d as { message: string }).message);
    } else {
      detail = JSON.stringify(d ?? body);
    }
  } catch {
    /* keep statusText */
  }
  return detail;
}

export async function createLibraryPack(draft: LibraryPackDraft): Promise<LibraryState> {
  /** Create a new user-authored pack. The id is derived from the label. */
  const res = await fetch("/api/libraries/packs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
  if (!res.ok) throw new Error(await libraryErrorDetail(res));
  return res.json();
}

export async function updateLibraryPack(
  id: string,
  draft: LibraryPackDraft,
): Promise<LibraryState> {
  /** Update a user-authored pack's contents. Refuses a built-in id. */
  const res = await fetch(`/api/libraries/packs/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
  if (!res.ok) throw new Error(await libraryErrorDetail(res));
  return res.json();
}

export function deleteLibraryPack(id: string): Promise<LibraryState> {
  /** Delete a user-authored pack. Refuses a shipped id. */
  return request<LibraryState>(`/api/libraries/packs/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function resetLibraryPack(id: string): Promise<LibraryState> {
  /** Restore a shipped pack to its bundled seed by deleting its shadow file. */
  return request<LibraryState>(`/api/libraries/packs/${encodeURIComponent(id)}/reset`, {
    method: "POST",
  });
}

export function setLibrarySelection(
  enabledPacks: string[],
  overrides: LibraryOverrides,
): Promise<LibraryState> {
  /** Set the active profile's enabled packs and overrides. */
  return request<LibraryState>("/api/libraries/selection", {
    method: "PUT",
    body: JSON.stringify({ enabled_packs: enabledPacks, overrides }),
  });
}

export function previewLibraryImpact(
  tagAliases: Record<string, string>,
): Promise<{ impacts: LibraryAliasImpact[] }> {
  /** What approving each of `tagAliases` would rewrite in the current master resume. */
  return request<{ impacts: LibraryAliasImpact[] }>("/api/libraries/impact", {
    method: "POST",
    body: JSON.stringify({ tag_aliases: tagAliases }),
  });
}

export function generateLibraryProposals(jdText?: string): Promise<LibraryState> {
  /** Draft new vocabulary suggestions from the resume's own gaps, optionally against
   * a pasted job description. */
  return request<LibraryState>("/api/libraries/proposals", {
    method: "POST",
    body: JSON.stringify({ jd_text: jdText ?? "" }),
  });
}

/** Thrown by `approveLibraryProposals` when approving would rewrite an existing bullet
 * tag and the caller has not yet confirmed that. Carries the exact impact so the UI can
 * show it before re-submitting with `acknowledgeRewrites: true`. */
export class LibraryApprovalConflict extends Error {
  impact: LibraryAliasImpact[];
  constructor(message: string, impact: LibraryAliasImpact[]) {
    super(message);
    this.name = "LibraryApprovalConflict";
    this.impact = impact;
  }
}

export async function approveLibraryProposals(
  proposalIds: string[],
  targetPackId: string,
  acknowledgeRewrites: boolean,
): Promise<LibraryState> {
  /** Fold selected proposals into an existing user-authored pack. Throws
   * `LibraryApprovalConflict` (409) when the change would rewrite an existing tag and
   * `acknowledgeRewrites` was not set. */
  const res = await fetch("/api/libraries/proposals/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      proposal_ids: proposalIds,
      target_pack_id: targetPackId,
      acknowledge_rewrites: acknowledgeRewrites,
    }),
  });
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    const detail = (body.detail ?? {}) as { message?: string; impact?: LibraryAliasImpact[] };
    throw new LibraryApprovalConflict(
      detail.message ?? "Approving this would rewrite existing tags.",
      detail.impact ?? [],
    );
  }
  if (!res.ok) {
    throw new Error(await libraryErrorDetail(res));
  }
  return res.json();
}

export function rejectLibraryProposals(proposalIds: string[]): Promise<LibraryState> {
  /** Decline selected proposals so they are never re-drafted. */
  return request<LibraryState>("/api/libraries/proposals/reject", {
    method: "POST",
    body: JSON.stringify({ proposal_ids: proposalIds }),
  });
}

/** A blank profile field that application forms ask for. */
export type ProfileGap = {
  key: string;
  label: string;
  section: string;
  /** Profile page tab holding the field. */
  path: string;
  /** Stored applications whose last fill met this question with the field blank. */
  seen_in: number;
};

export type ApplicantProfileResponse = {
  workspace_id: string | null;
  profile: ApplicantProfile;
  seeded: boolean;
  workday_password_set: boolean;
  gaps?: ProfileGap[];
  /** Answers used when a harmless field is blank, keyed by canonical field. */
  defaults?: Record<string, string>;
};

/** Load the applicant form-filling profile for the active workspace. */
export function getApplicantProfile(): Promise<ApplicantProfileResponse> {
  return request("/api/applicant-profile");
}

/** Persist the applicant form-filling profile. */
/** Store the transcript PDF fills attach to "Transcript" uploads. */
export async function uploadTranscript(file: File): Promise<ApplicantProfileResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/applicant-profile/transcript", { method: "POST", body: form });
  if (!res.ok) throw await apiError(res);
  return res.json() as Promise<ApplicantProfileResponse>;
}

export function deleteTranscript(): Promise<ApplicantProfileResponse> {
  return request("/api/applicant-profile/transcript", { method: "DELETE" });
}

export function putApplicantProfile(profile: ApplicantProfile): Promise<ApplicantProfileResponse> {
  return request("/api/applicant-profile", {
    method: "PUT",
    body: JSON.stringify({ profile }),
  });
}

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

/** Last body and ETag per URL, for `conditionalGet`. */
const etagCache = new Map<string, { etag: string; body: unknown }>();

/**
 * GET that sends `If-None-Match` and, on a 304, returns the very object it returned
 * last time: a poll that finds nothing new hands React the same reference, so the
 * table does not re-render.
 */
export async function conditionalGet<T>(path: string): Promise<T> {
  const cached = etagCache.get(path);
  const res = await fetch(path, {
    headers: cached ? { "If-None-Match": cached.etag } : {},
  });
  if (res.status === 304 && cached) return cached.body as T;
  if (!res.ok) throw await apiError(res);
  const body = (await res.json()) as T;
  const etag = res.headers.get("ETag");
  if (etag) {
    if (etagCache.size > 50) etagCache.clear();
    etagCache.set(path, { etag, body });
  }
  return body;
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
  summary: Record<string, unknown> | null;
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

/** Open browser tab ids; `reachable: false` means tab state is unknown. */
export function getOpenTabs(): Promise<{ reachable: boolean; target_ids: string[] }> {
  return request("/api/applications/open-tabs");
}

/** CSV download URL for the applications tracker export. */
export function applicationsExportUrl(): string {
  return "/api/applications/export.csv";
}

export type OnboardingField = "" | "cs" | "business" | "engineering" | "other";

export interface OnboardingState {
  step: "field" | "model" | "resume" | "review" | "basics" | "done";
  field: OnboardingField;
  completed: boolean;
  skipped: boolean;
  updated_at: string;
}

/** Where the first-run wizard left off for the active profile. */
export function getOnboarding(): Promise<OnboardingState> {
  return request("/api/onboarding");
}

export function putOnboarding(
  patch: Partial<Pick<OnboardingState, "step" | "field" | "completed" | "skipped">>,
): Promise<OnboardingState> {
  return request("/api/onboarding", {
    method: "PUT",
    body: JSON.stringify(patch),
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

/** One answer remembered from a review correction (`GET /api/answer-memory`). */
export type SavedAnswer = {
  id: number;
  label: string;
  answer: string;
  ats: string;
  company: string;
  source: string;
  uses: number;
  updated_at: string;
};

export async function fetchSavedAnswers(): Promise<SavedAnswer[]> {
  return (await request<{ answers: SavedAnswer[] }>("/api/answer-memory")).answers;
}

export function updateSavedAnswer(id: number, answer: string): Promise<SavedAnswer> {
  return request(`/api/answer-memory/${id}`, {
    method: "PUT",
    body: JSON.stringify({ answer }),
  });
}

export async function deleteSavedAnswer(id: number): Promise<SavedAnswer[]> {
  return (
    await request<{ answers: SavedAnswer[] }>(`/api/answer-memory/${id}`, { method: "DELETE" })
  ).answers;
}

// --- Auto-submit guard rails (P4-S) ---------------------------------------------------

export type AutomationState = {
  paused: boolean;
  changed_at: string;
  /** Automatic submits in the last 24 hours, against `max_per_day`. */
  auto_submits_24h: number;
  max_per_day: number;
};

export function fetchAutomation(): Promise<AutomationState> {
  return request<AutomationState>("/api/automation");
}

export function setAutomationPaused(paused: boolean): Promise<AutomationState> {
  return request<AutomationState>("/api/automation", {
    method: "PUT",
    body: JSON.stringify({ paused }),
  });
}

/** One automatic submit's audit folder: screenshots and filled fields around the click. */
export type SubmitEvidence = {
  stamp: string;
  files: string[];
  url: string;
  status: string;
  confirmation: string;
};

export async function fetchSubmitEvidence(applicationId: string): Promise<SubmitEvidence[]> {
  return (
    await request<{ evidence: SubmitEvidence[] }>(
      `/api/applications/${encodeURIComponent(applicationId)}/submit-evidence`,
    )
  ).evidence;
}

export function submitEvidenceFileUrl(applicationId: string, stamp: string, name: string): string {
  return `/api/applications/${encodeURIComponent(applicationId)}/submit-evidence/${encodeURIComponent(stamp)}/${encodeURIComponent(name)}`;
}
