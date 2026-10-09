import type { ApplicantProfile, NoticeUnit, OnboardingState, VisaStatus } from "../api";
import type { DatePrecision } from "./dates";

/** Form labels for profile fields; anything unlisted is its key in words. */
export const PROFILE_LABELS: Partial<Record<keyof ApplicantProfile | string, string>> = {
  first_name: "Legal first name",
  middle_name: "Middle name",
  last_name: "Legal last name",
  preferred_name: "Preferred name",
  pronouns: "Pronouns",
  email: "Email",
  phone: "Phone",
  linkedin_url: "LinkedIn URL",
  github_url: "GitHub URL",
  portfolio_url: "Portfolio URL",
  address_line1: "Address line 1",
  address_line2: "Address line 2",
  city: "City",
  state: "State or province",
  postal_code: "Postal code",
  country: "Country",
  phone_country_code: "Phone country",
  phone_country_region: "Phone country",
  phone_device_type: "Phone device type",
  authorization_country: "Country you're authorized in",
  authorized_to_work: "Authorized to work",
  requires_sponsorship_now: "Need sponsorship now",
  requires_sponsorship_future: "Need sponsorship in the future",
  f1_opt_eligible: "Eligible for F-1 OPT/CPT",
  earliest_start: "Earliest start",
  notice_period: "Notice period",
  location_preference: "Location preference",
  willing_to_relocate: "Willing to relocate",
  highest_education_obtained: "Highest education completed",
  salary_expectation: "Salary expectation (text)",
  salary_hourly_min: "Hourly minimum ($)",
  salary_hourly_max: "Hourly maximum ($)",
  salary_yearly_min: "Yearly minimum ($)",
  salary_yearly_max: "Yearly maximum ($)",
  referred_by: "Referred by",
  how_heard: "How you heard about the job",
  workday_email: "Workday email",
  workday_password: "Workday password",
  over_18: "18 or older",
  relatives_at_company: "Relatives at the company",
  subject_to_noncompete: "Subject to a non-compete agreement",
  portfolio_only_when_asked: "Portfolio only when asked",
  visa_status: "Visa status",
  graduation_date: "Expected graduation",
  class_year: "Class standing",
  high_school_graduation_year: "High-school graduation year",
  auto_accept_routine_acknowledgements: "Accept routine privacy and read-notice acknowledgements",
  gpa_display: "GPA shown on forms",
  school_email: "School email",
  security_clearance: "Security clearance",
  drivers_license: "Driver's license",
  hours_per_week_available: "Hours per week available",
};

export function fieldLabel(key: string): string {
  return PROFILE_LABELS[key] ?? key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
}

export const VISA_OPTIONS: { value: VisaStatus; label: string }[] = [
  { value: "", label: "Not set" },
  { value: "none", label: "No visa needed (citizen or permanent resident)" },
  { value: "f1", label: "F-1 student" },
  { value: "f1_cpt", label: "F-1 (CPT)" },
  { value: "f1_opt", label: "F-1 (OPT)" },
  { value: "f1_stem_opt", label: "F-1 (STEM OPT)" },
  { value: "h1b", label: "H-1B" },
  { value: "h4_ead", label: "H-4 EAD" },
  { value: "other", label: "Other" },
];

/** Client mirror of `profile.sponsorship_from_visa`: [now, future] or null. */
export function sponsorshipFromVisa(visa: VisaStatus | undefined): [boolean, boolean] | null {
  switch (visa) {
    case "none":
      return [false, false];
    case "f1":
    case "f1_cpt":
    case "f1_opt":
    case "f1_stem_opt":
    case "h4_ead":
      return [false, true];
    case "h1b":
      return [true, true];
    default:
      return null;
  }
}

/** Top-level profile keys whose draft value differs from the saved one. */
export function changedKeys(saved: ApplicantProfile | null, draft: ApplicantProfile | null) {
  if (!saved || !draft) return [];
  const keys = new Set([...Object.keys(saved), ...Object.keys(draft)]) as Set<
    keyof ApplicantProfile
  >;
  return [...keys].filter((key) => JSON.stringify(saved[key]) !== JSON.stringify(draft[key]));
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function validUrl(value: string): boolean {
  try {
    const url = new URL(/^[a-z]+:\/\//i.test(value) ? value : `https://${value}`);
    return /^https?:$/.test(url.protocol) && url.hostname.includes(".");
  } catch {
    return false;
  }
}

/** Field -> problem, for fields the student filled in wrongly. Blank is never an error. */
export function validateProfile(profile: ApplicantProfile): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const key of ["email", "school_email", "workday_email"] as const) {
    const value = (profile[key] ?? "").trim();
    if (value && !EMAIL.test(value)) errors[key] = "Enter an email like name@example.com.";
  }
  if (
    profile.school_email?.trim() &&
    !errors.school_email &&
    !/\.edu$/i.test(profile.school_email.trim())
  )
    errors.school_email = "Use your school address (ending in .edu).";
  const phone = profile.phone.trim().replace(/\s*ext(ension)?\.?\s*/i, " x");
  if (phone) {
    const digits = phone.replace(/\D/g, "").length;
    if (digits < 7 || digits > 15 || /[^\d\s()+.\-x]/i.test(phone))
      errors.phone = "Enter a phone number with 7–15 digits.";
  }
  for (const key of ["linkedin_url", "github_url", "portfolio_url"] as const) {
    const value = (profile[key] ?? "").trim();
    if (value && !validUrl(value)) errors[key] = "Enter a web address like linkedin.com/in/you.";
  }
  for (const unit of ["hourly", "yearly"] as const) {
    const min = profile[`salary_${unit}_min`];
    const max = profile[`salary_${unit}_max`];
    if (min != null && min < 0) errors[`salary_${unit}_min`] = "Can't be negative.";
    if (max != null && max < 0) errors[`salary_${unit}_max`] = "Can't be negative.";
    if (min != null && max != null && min > max)
      errors[`salary_${unit}_max`] = "The maximum must be at least the minimum.";
  }
  if (profile.graduation_date && !/^\d{4}-(0[1-9]|1[0-2])$/.test(profile.graduation_date))
    errors.graduation_date = "Pick a month and year.";
  if (profile.high_school_graduation_year && !/^\d{4}$/.test(profile.high_school_graduation_year))
    errors.high_school_graduation_year = "Enter a four-digit year or leave blank for Auto.";
  if (profile.earliest_start && !/^\d{4}-(0[1-9]|1[0-2])-\d{2}$/.test(profile.earliest_start))
    errors.earliest_start = "Pick a month, year and day.";
  const hours = profile.hours_per_week_available;
  if (hours != null && (!Number.isInteger(hours) || hours < 0 || hours > 80))
    errors.hours_per_week_available = "Enter whole hours from 0 to 80.";
  return errors;
}

/** Profile sub-tab that holds `key` (for jumping to the first invalid field). */
export function tabForField(key: string): "personal" | "application" {
  return ["first_name", "middle_name", "last_name", "preferred_name", "email", "phone"].includes(
    key,
  ) ||
    (key.endsWith("_url") && key !== "portfolio_url")
    ? "personal"
    : "application";
}

/** One collapsible block on the Application details tab. `id` is the backend section name
 * (`packet.PROFILE_FIELDS`), so a profile gap opens the group that holds it. */
export type ProfileGroup = { id: string; title: string; fields: (keyof ApplicantProfile)[] };

export const PROFILE_GROUPS: ProfileGroup[] = [
  {
    id: "Work authorization and sponsorship",
    title: "Work authorization",
    fields: [
      "visa_status",
      "work_authorization",
      "authorization_country",
      "authorized_to_work",
      "requires_sponsorship_now",
      "requires_sponsorship_future",
      "f1_opt_eligible",
    ],
  },
  {
    id: "Education",
    title: "Education",
    fields: [
      "graduation_date",
      "class_year",
      "high_school_graduation_year",
      "gpa_display",
      "highest_education_obtained",
      "school_email",
    ],
  },
  {
    id: "Availability and location preferences",
    title: "Availability",
    fields: [
      "earliest_start",
      "notice_period",
      "hours_per_week_available",
      "willing_to_relocate",
      "location_preference",
      "drivers_license",
      "security_clearance",
      "subject_to_noncompete",
    ],
  },
  {
    id: "Address and phone details",
    title: "Address and phone",
    fields: [
      "address_line1",
      "address_line2",
      "city",
      "state",
      "postal_code",
      "country",
      "phone_country_code",
      "phone_device_type",
    ],
  },
  {
    id: "Salary",
    title: "Compensation",
    fields: [
      "salary_hourly_min",
      "salary_hourly_max",
      "salary_yearly_min",
      "salary_yearly_max",
      "salary_expectation",
    ],
  },
  {
    id: "Voluntary information",
    title: "Demographics (optional)",
    fields: ["pronouns", "over_18", "relatives_at_company"],
  },
  { id: "Languages", title: "Languages", fields: [] },
  { id: "Application accounts", title: "Accounts", fields: ["workday_email", "workday_password"] },
  {
    id: "Saved answers and other preferences",
    title: "Saved answers",
    fields: [
      "referred_by",
      "how_heard",
      "portfolio_url",
      "portfolio_only_when_asked",
      "auto_accept_routine_acknowledgements",
    ],
  },
];

/** The group that holds `key`, if it is on the Application details tab. */
export function groupForField(key: string): string | undefined {
  return PROFILE_GROUPS.find((group) => group.fields.includes(key as keyof ApplicantProfile))?.id;
}

/** The "Remembered answers" tile: collapsible like the groups, but not a profile section. */
export const REMEMBERED_ANSWERS_GROUP = "remembered-answers";

/** Every collapsible block on the Application details tab. */
export const ALL_PROFILE_GROUP_IDS = [
  ...PROFILE_GROUPS.map((group) => group.id),
  REMEMBERED_ANSWERS_GROUP,
];

/**
 * Whether Application details should open fully expanded: while first-run setup is still
 * going (neither completed nor skipped), or when a link asks for it with `?setup=1`.
 * Unknown setup state (still loading, or the request failed) counts as finished.
 */
export function inSetup(
  onboarding: Pick<OnboardingState, "completed" | "skipped"> | null,
  search = "",
): boolean {
  if (new URLSearchParams(search).get("setup") === "1") return true;
  return onboarding != null && !onboarding.completed && !onboarding.skipped;
}

/** The groups open on arrival: all of them during setup, none after it. */
export function initialOpenGroups(setup: boolean): Set<string> {
  return new Set(setup ? ALL_PROFILE_GROUP_IDS : []);
}

/** `open` with group `id` opened or closed; the same set when nothing changes. */
export function withGroupOpen(open: Set<string>, id: string, isOpen: boolean): Set<string> {
  if (open.has(id) === isOpen) return open;
  const next = new Set(open);
  if (isOpen) next.add(id);
  else next.delete(id);
  return next;
}

/** Yes/No questions: rendered as a three-way select (blank = not set). */
export const BOOLEAN_FIELDS = new Set<string>([
  "authorized_to_work",
  "requires_sponsorship_now",
  "requires_sponsorship_future",
  "f1_opt_eligible",
  "willing_to_relocate",
  "over_18",
  "relatives_at_company",
  "drivers_license",
  "subject_to_noncompete",
]);

/** Plain on/off settings (never blank on the server). */
export const CHECKBOX_FIELDS = new Set<string>([
  "portfolio_only_when_asked",
  "auto_accept_routine_acknowledgements",
]);

/** Gap keys (`packet.PROFILE_FIELDS`) whose profile field is named differently. */
export const GAP_FIELD_ALIASES: Record<string, string> = {
  requires_sponsorship: "requires_sponsorship_now",
  hours_per_week: "hours_per_week_available",
  graduation_month: "graduation_date",
  phone_country_region: "phone_country_code",
  noncompete: "subject_to_noncompete",
};

/** Date fields, edited as a month select plus typed year (and day). */
export const DATE_FIELDS: Partial<Record<keyof ApplicantProfile, DatePrecision>> = {
  graduation_date: "month",
  earliest_start: "day",
};

/** "2 weeks" for a notice period; blank when there is no number. */
export function noticeLabel(value: number | null | undefined, unit: NoticeUnit): string {
  if (value == null) return "";
  if (value === 0) return "Immediately";
  return `${value} ${unit}${value === 1 ? "" : "s"}`;
}

export const NUMBER_FIELDS = new Set<string>([
  "salary_hourly_min",
  "salary_hourly_max",
  "salary_yearly_min",
  "salary_yearly_max",
  "hours_per_week_available",
]);

/** Fixed-choice fields, as [value, label] (the first option is "not set"). */
export const CHOICE_FIELDS: Record<string, [string, string][]> = {
  visa_status: VISA_OPTIONS.map((option) => [option.value, option.label]),
  work_authorization: [
    ["", "Not set"],
    ["citizen", "Citizen"],
    ["permanent_resident", "Permanent resident"],
    ["visa_holder", "Visa holder"],
    ["other", "Other"],
  ],
  class_year: [
    ["", "Auto from graduation month"],
    ["freshman", "Freshman"],
    ["sophomore", "Sophomore"],
    ["junior", "Junior"],
    ["senior", "Senior"],
    ["graduate", "Graduate student"],
  ],
  security_clearance: [
    ["", "Not set"],
    ["none", "None"],
    ["eligible", "Eligible to obtain one"],
    ["secret", "Secret"],
    ["top_secret", "Top Secret"],
  ],
};

/** Client mirror of `packet.class_year_for` (undergraduate standing only). */
export function classYearFor(graduation: string | undefined, today = new Date()): string | null {
  const match = /^(\d{4})-(\d{2})$/.exec((graduation ?? "").trim());
  if (!match) return null;
  const months =
    (Number(match[1]) - today.getFullYear()) * 12 + Number(match[2]) - (today.getMonth() + 1);
  if (months < 0) return null;
  return ["Senior", "Junior", "Sophomore", "Freshman"][Math.min(Math.floor(months / 12), 3)];
}
