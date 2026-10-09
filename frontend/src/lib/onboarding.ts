import type {
  ApplySettings,
  CatalogEntry,
  OnboardingField,
  OnboardingState,
  SourceCatalog,
  SourceConfig,
  SourceField,
} from "../api";
import type { Bullet, MasterResume } from "./resumeEdit";
import { DEFAULT_CATALOG_IDS, entriesForFields, sourceFromCatalog } from "./sources";
import { newWatchlistSource } from "./watchlist";

export const ONBOARDING_STEPS = [
  { id: "field", label: "Your field" },
  { id: "tools", label: "AI & browser" },
  { id: "resume", label: "Your resume" },
  { id: "personal", label: "Personal info" },
  { id: "content", label: "Resume content" },
  { id: "application", label: "Application details" },
  { id: "review", label: "Review" },
  { id: "done", label: "Done" },
] as const;

export type OnboardingStep = (typeof ONBOARDING_STEPS)[number]["id"];

export function stepIndex(step: OnboardingStep): number {
  return ONBOARDING_STEPS.findIndex((s) => s.id === step);
}

/** What stops working when a step is skipped; shown before the skip goes through. */
export const SKIP_WARNINGS: Record<Exclude<OnboardingStep, "review" | "done">, string> = {
  field:
    "Without a target field, skill matching uses general tech words only and no job lists are searched for you.",
  tools: "Tailoring and autofill won't run until a model is connected.",
  resume: "There's nothing to tailor yet, and no template to keep your resume's design.",
  personal: "Your resume header and the contact fields on application forms will be blank.",
  content: "Tailored resumes can only use the entries and bullets you've added.",
  application: "Autofill will stop at these questions and wait for you to answer them.",
};

/** Personal-information fields the step requires (beyond being well formed). */
export const REQUIRED_PERSONAL = ["first_name", "last_name", "email", "phone"] as const;

/**
 * Whether the Personal step's required fields are filled and none is malformed. A field
 * left blank still counts when forms fall back to something for it: the resume header's
 * email and phone, or the server's per-field fallbacks (names split from the resume).
 */
export function personalComplete(
  draft: Partial<Record<(typeof REQUIRED_PERSONAL)[number], string>> | null,
  errors: Record<string, string>,
  contact?: { email?: string; phone?: string } | null,
  fallbacks: Record<string, string> = {},
): boolean {
  if (!draft) return false;
  const resumeEmail = contact?.email === "you@example.com" ? "" : contact?.email;
  const value = (key: (typeof REQUIRED_PERSONAL)[number]) =>
    draft[key]?.trim() ||
    fallbacks[key]?.trim() ||
    (key === "email" ? resumeEmail?.trim() : key === "phone" ? contact?.phone?.trim() : "");
  return REQUIRED_PERSONAL.every((key) => !!value(key) && !errors[key]);
}

/**
 * Whether the resume content is usable: at least one bullet to tailor and nothing
 * blocking (a missing name). Missing dates and empty entries are warnings: they weaken a resume but never stop a run.
 */
export function contentComplete(review: ResumeReview): boolean {
  return review.bullets > 0 && review.blocking.length === 0;
}

/** Application-form gaps the draft still leaves blank (``keys`` are already aliased). */
export function openGaps(keys: string[], draft: Record<string, unknown> | null): string[] {
  if (!draft) return keys;
  return keys.filter((key) => {
    const value = draft[key];
    return value === null || value === undefined || (typeof value === "string" && !value.trim());
  });
}

/**
 * Job-source fields each target field starts with; the student adds or drops any. The
 * study field is kept beside it for the job-list presets that still key on it.
 */
const TARGET_SOURCES: Record<string, { fields: SourceField[]; study: OnboardingField }> = {
  general: { fields: [], study: "other" },
  "software-data": { fields: ["swe", "data"], study: "cs" },
  "finance-consulting": { fields: ["finance", "consulting", "quant"], study: "business" },
  accounting: { fields: ["finance", "business"], study: "business" },
  marketing: { fields: ["business", "product"], study: "business" },
  "operations-supply-chain": { fields: ["business"], study: "business" },
};

/** Source fields preselected for a target field (none for General or an unknown id). */
export function sourceFieldsForTarget(target: string | null | undefined): SourceField[] {
  return target ? [...(TARGET_SOURCES[target]?.fields ?? [])] : [];
}

/** The legacy study field a target field implies (drives the business watchlist). */
export function studyFieldForTarget(target: string | null | undefined): OnboardingField {
  return target ? (TARGET_SOURCES[target]?.study ?? "other") : "";
}

/**
 * Catalog entries a set of source fields preselects, in catalog order. Keyword searches are
 * left out: they return nothing until the student connects an API key, so onboarding does
 * not add them silently (the Sources page offers them under "Recommended").
 */
export function suggestedEntries(catalog: SourceCatalog, fields: SourceField[]): CatalogEntry[] {
  return entriesForFields(catalog, fields).filter((entry) => entry.template.kind !== "job_search");
}

/**
 * The profile's sources after onboarding picks catalog entries: the catalog-managed ones
 * (the built-in defaults and earlier catalog picks) are replaced by ``chosen``; sources
 * the student made themselves stay. Business also gets an empty company watchlist.
 */
export function sourcesFromCatalogPicks(
  existing: SourceConfig[],
  chosen: CatalogEntry[],
  field: OnboardingField,
): SourceConfig[] {
  const kept = existing.filter((s) => !s.catalog_id && !DEFAULT_CATALOG_IDS.includes(s.id));
  const out = [...kept];
  for (const entry of chosen) out.push(sourceFromCatalog(entry, out));
  if (field === "business" && !out.some((s) => s.kind === "ats_board")) {
    out.push(newWatchlistSource(undefined, out));
  }
  return out;
}

/**
 * ``apply`` with the chosen sources and the job fields they came from. The fields are what
 * the Sources tab's "Recommended for your fields" strip reads later.
 */
export function withSourceChoice(
  apply: ApplySettings,
  sources: SourceConfig[],
  fields: SourceField[],
): ApplySettings {
  return { ...apply, sources, fields: [...fields] };
}

export interface ResumeReview {
  entries: number;
  bullets: number;
  sections: { title: string; count: number }[];
  warnings: string[];
  /** The warnings that make the content unusable for tailoring (subset of ``warnings``). */
  blocking: string[];
}

/** What the Review step shows about the imported master resume. */
export function reviewResume(resume: MasterResume | null): ResumeReview {
  const review: ResumeReview = {
    entries: 0,
    bullets: 0,
    sections: [],
    warnings: [],
    blocking: [],
  };
  if (!resume) return review;
  for (const section of resume.sections) {
    review.sections.push({ title: section.title, count: section.entries.length });
    if (section.kind === "experience" || section.kind === "project") {
      const entries: { name: string; dated: string; bullets: Bullet[] }[] =
        section.kind === "experience"
          ? section.entries.map((e) => ({
              name: e.company,
              dated: e.start || e.end,
              bullets: e.bullets,
            }))
          : // Undated projects are normal on a resume; only jobs need dates.
            section.entries.map((p) => ({ name: p.name, dated: "n/a", bullets: p.bullets }));
      review.entries += entries.length;
      for (const { name, dated, bullets } of entries) {
        review.bullets += bullets.length;
        if (!dated) review.warnings.push(`No dates found for ${name || "an entry"}.`);
        if (bullets.length === 0) review.warnings.push(`${name || "An entry"} has no bullets.`);
      }
    } else if (section.kind === "list") {
      review.entries += section.entries.length;
    }
  }
  if (!resume.contact.name.trim() || resume.contact.name === "Your Name")
    review.blocking.unshift("Your name is missing.");
  review.warnings.unshift(...review.blocking);
  return review;
}

/** Whether first-run setup is still running (not finished, not skipped). */
export function setupActive(state: Pick<OnboardingState, "completed" | "skipped"> | null): boolean {
  return !!state && !state.completed && !state.skipped;
}

/** Whether ``pathname`` should bounce to the wizard: every page is closed during setup. */
export function needsWelcome(state: OnboardingState | null, pathname: string): boolean {
  return setupActive(state) && !pathname.startsWith("/welcome");
}

/** One Review row: a profile answer as the student typed or picked it. */
export type SummaryRow = { label: string; value: string };

/**
 * The application answers worth echoing on the Review step: filled fields only, in
 * Profile group order, select codes shown by their label and booleans as Yes/No.
 */
export function applicationSummary(
  draft: Record<string, unknown> | null,
  groups: { fields: string[] }[],
  choices: Record<string, [string, string][]>,
  label: (key: string) => string,
): SummaryRow[] {
  if (!draft) return [];
  const rows: SummaryRow[] = [];
  for (const key of groups.flatMap((g) => g.fields)) {
    const value = draft[key];
    if (value === null || value === undefined || value === "") continue;
    const shown =
      typeof value === "boolean"
        ? value
          ? "Yes"
          : "No"
        : (choices[key]?.find(([code]) => code === String(value))?.[1] ?? String(value));
    rows.push({ label: label(key), value: shown });
  }
  return rows;
}
