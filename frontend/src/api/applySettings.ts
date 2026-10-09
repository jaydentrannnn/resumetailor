/** Apply settings, the applicant profile, saved answers, automation, submit evidence. */

import { apiError, request } from "./core";
import type { SourceField } from "./sources";

export type ScreenSettings = {
  allowed_seniority: string[];
  block_patterns: string[];
};

export type BoardAts = "greenhouse" | "lever" | "ashby" | "smartrecruiters" | "workday";

/** One company job board on a watchlist source. */
export type BoardConfig = { ats: BoardAts; slug: string; company: string };

export type SourceKind =
  "simplify_html" | "pipe_table" | "company_link_table" | "ats_board" | "job_search";

export type SourceConfig = {
  id: string;
  kind: SourceKind;
  /** Display name; falls back to `id` when empty. */
  name?: string;
  /** Source-catalog entry this source was added from, and that entry's version then. */
  catalog_id?: string | null;
  catalog_version?: string | null;
  url: string;
  categories: string[];
  enabled: boolean;
  /** Watchlist (`ats_board`) sources only. */
  boards?: BoardConfig[];
  include?: string[];
  exclude?: string[];
  locations?: string[];
  /** Skip the global keep words (`ApplySettings.source_filters.include`) for this source. */
  ignore_global_include?: boolean;
  /** Widens the funnel-wide age limit (the longer wins); watchlists default to 7 days, job_search 14 days. */
  max_age_days?: number | null;
  /** Keyword job search (`job_search`) sources only. */
  provider?: "adzuna" | "usajobs" | null;
  /** One or more comma-separated phrases (max 5), each searched separately. */
  query?: string;
  location?: string;
  country?: string;
};

/** Filters for every source: added to each source's own words before it is fetched. */
export type SourceFilters = {
  include: string[];
  exclude: string[];
  locations: string[];
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
  /** Missing on settings saved by an older server. */
  source_filters?: SourceFilters;
  max_age_days: number;
  /** Job fields this profile searches for; drives "Recommended for your fields". */
  fields?: SourceField[];
  exclude_advanced_degree: boolean;
  exclude_citizenship_required: boolean;
  exclude_no_sponsorship: boolean;
  max_new_per_day: number;
  screen: ScreenSettings;
  eligibility: EligibilitySettings;
  auto_submit_ats: string[];
  auto_submit_max_per_run: number;
  max_parallel_fills: number;
  /** Rolling 24-hour caps on automatic submits; 0 means none. */
  auto_submit_max_per_day: number;
  auto_submit_max_per_company_per_day: number;
  auto_submit_enabled: boolean;
  blocker_mode: "pause" | "continue";
  reuse_threshold: number;
  cover_letter: boolean;
  // Provider + model for the funnel's own extract/answer calls — separate from the
  // Tailor model setting. See `ApplySettings.model_spec` on the backend.
  model_provider: "ollama" | "ollama-cloud" | "lmstudio" | "gemini" | "anthropic";
  model_name: string;
  /** Browser the app starts for Fill and job fetches; null picks the first installed. */
  browser?: BrowserId | null;
};

export type BrowserId = "edge" | "chrome" | "comet";

/** Veteran self-identification (`profile.VeteranStatus`); "" skips the question. */
export type VeteranStatus = "" | "protected" | "veteran_not_protected" | "not_veteran" | "decline";

export const VETERAN_OPTIONS: { value: VeteranStatus; label: string }[] = [
  { value: "", label: "Not set (skip the question)" },
  { value: "not_veteran", label: "I am not a veteran" },
  { value: "veteran_not_protected", label: "I am a veteran, but not a protected veteran" },
  { value: "protected", label: "I am a protected veteran" },
  { value: "decline", label: "Decline to self-identify" },
];

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
  /** Display string derived from the number and unit ("2 weeks"); the server keeps it in sync. */
  notice_period?: string;
  notice_period_value?: number | null;
  notice_period_unit?: NoticeUnit;
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
  subject_to_noncompete: boolean | null;
  referred_by: string;
  how_heard: string;
  workday_email?: string;
  workday_password?: string;
  eeo: {
    gender: string;
    race: string;
    race_detail?: string;
    hispanic_latino?: boolean | null;
    /** A category (`profile.VeteranStatus`), matched to each form's own wording. */
    veteran: VeteranStatus;
    /** The older free-text answer this category was converted from; "" once confirmed. */
    veteran_legacy?: string;
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
  /** Server-owned: set only by the portfolio upload route. */
  portfolio_path?: string;
  security_clearance?: "" | "none" | "eligible" | "secret" | "top_secret";
  drivers_license?: boolean | null;
  hours_per_week_available?: number | null;
  school_email?: string;
};

export type NoticeUnit = "day" | "week" | "month";

export type VisaStatus =
  "" | "none" | "f1" | "f1_opt" | "f1_stem_opt" | "f1_cpt" | "h1b" | "h4_ead" | "other";

export type ApplicantLanguage = {
  language: string;
  fluent: boolean;
  levels: Record<string, string>;
};

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
  /** What a blank field falls back to from the resume, by profile field ("June 2027"). */
  fallbacks?: Record<string, string>;
  /** Custom answers that restate a built-in field: question -> profile field. */
  custom_answer_duplicates?: Record<string, string>;
};

/** Fixed option lists for the Profile pickers (`GET /api/reference/profile-options`). */
export type ProfileOptions = {
  education_levels: string[];
  education_level_aliases: Record<string, string>;
  countries: { code: string; name: string; dial: string; aliases: string[] }[];
  subdivisions: Record<string, { code: string; name: string }[]>;
  pronouns: string[];
  genders: string[];
  races: string[];
  race_details: Record<string, string[]>;
  disability: string[];
};

export function fetchProfileOptions(): Promise<ProfileOptions> {
  return request("/api/reference/profile-options");
}

/** Fold a custom answer into the built-in field it restates, then drop the entry. */
export function mergeCustomAnswer(question: string): Promise<ApplicantProfileResponse> {
  return request("/api/applicant-profile/merge-custom-answer", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

/** Load the applicant form-filling profile for the active workspace. */
export function getApplicantProfile(): Promise<ApplicantProfileResponse> {
  return request("/api/applicant-profile");
}

/** PDFs fills attach to matching upload fields ("Transcript", "Portfolio"). */
export type ProfileDocument = "transcript" | "portfolio";

/** Store a profile PDF; the server records its path in the profile. */
export async function uploadProfileDocument(
  kind: ProfileDocument,
  file: File,
): Promise<ApplicantProfileResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/applicant-profile/${kind}`, { method: "POST", body: form });
  if (!res.ok) throw await apiError(res);
  return res.json() as Promise<ApplicantProfileResponse>;
}

export function deleteProfileDocument(kind: ProfileDocument): Promise<ApplicantProfileResponse> {
  return request(`/api/applicant-profile/${kind}`, { method: "DELETE" });
}

/** Persist the applicant form-filling profile. */
export function putApplicantProfile(profile: ApplicantProfile): Promise<ApplicantProfileResponse> {
  return request("/api/applicant-profile", {
    method: "PUT",
    body: JSON.stringify({ profile }),
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
  /** Every stored row for this question (one per site); edits and deletes cover all. */
  ids?: number[];
  /** The ATSs the question was answered on. */
  sites?: string[];
  /** The sites' answers disagree; the one shown is the most recent. */
  differs?: boolean;
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

/** A dropdown/radio choice the autofill model made, reused until forgotten. */
export type AIChoice = { key: string; label: string; answer: string };

export async function fetchAIChoices(): Promise<AIChoice[]> {
  return (await request<{ choices: AIChoice[] }>("/api/answer-memory/ai-choices")).choices;
}

export async function forgetAIChoice(key: string): Promise<AIChoice[]> {
  return (
    await request<{ choices: AIChoice[] }>(
      `/api/answer-memory/ai-choices/${encodeURIComponent(key)}`,
      { method: "DELETE" },
    )
  ).choices;
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
