import type {
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
  { id: "model", label: "AI model" },
  { id: "resume", label: "Your resume" },
  { id: "review", label: "Review" },
  { id: "basics", label: "Application basics" },
  { id: "done", label: "Done" },
] as const;

export type OnboardingStep = (typeof ONBOARDING_STEPS)[number]["id"];

export function stepIndex(step: OnboardingStep): number {
  return ONBOARDING_STEPS.findIndex((s) => s.id === step);
}

export const FIELDS: { id: Exclude<OnboardingField, "">; label: string; description: string }[] = [
  {
    id: "business",
    label: "Business, Finance or Economics",
    description: "Finance, consulting, accounting, marketing and product roles.",
  },
  {
    id: "cs",
    label: "Computer Science or Data Science",
    description: "Software, data, machine learning and analytics roles.",
  },
  {
    id: "engineering",
    label: "Engineering",
    description: "Hardware, electrical, mechanical and software engineering roles.",
  },
  { id: "other", label: "Something else", description: "You can tune everything later." },
];

/** Skill vocabularies the field choice owns; any other enabled pack is left alone. */
const FIELD_PACKS: Record<Exclude<OnboardingField, "">, string[]> = {
  business: ["core-tech", "finance-consulting", "accounting", "marketing", "ops-supply-chain"],
  cs: ["core-tech"],
  engineering: ["core-tech"],
  other: ["core-tech"],
};
const MANAGED_PACKS = new Set(Object.values(FIELD_PACKS).flat());

/** Enabled packs after choosing ``field``: the field's packs plus any the user added. */
export function packsForField(
  enabled: string[],
  field: OnboardingField,
  available: string[],
): string[] {
  if (!field) return enabled;
  const kept = enabled.filter((id) => !MANAGED_PACKS.has(id));
  const wanted = FIELD_PACKS[field].filter((id) => available.includes(id));
  return [...wanted, ...kept];
}

/** The job-source fields each study field starts with; the student adds or drops any. */
const FIELD_SOURCE_FIELDS: Record<Exclude<OnboardingField, "">, SourceField[]> = {
  business: ["finance", "consulting", "product", "business", "quant"],
  cs: ["swe", "data"],
  engineering: ["hardware", "swe"],
  other: [],
};

/** Source fields preselected for ``field`` (empty for "something else" or no choice). */
export function sourceFieldsFor(field: OnboardingField): SourceField[] {
  return field ? [...FIELD_SOURCE_FIELDS[field]] : [];
}

/** Catalog entries a set of source fields preselects, in catalog order. */
export function suggestedEntries(catalog: SourceCatalog, fields: SourceField[]): CatalogEntry[] {
  return entriesForFields(catalog, fields);
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

/** Job-board categories per field (fallback when the catalog cannot be fetched). Names match the Simplify README headings exactly
 * (checked against both READMEs); a category that is not in the README finds nothing. */
const FIELD_CATEGORIES: Partial<
  Record<Exclude<OnboardingField, "">, Record<string, string[] | false>>
> = {
  business: {
    "simplify-internships": [
      "Quantitative Finance Internship Roles",
      "Product Management Internship Roles",
    ],
    "simplify-newgrad": [
      "Quantitative Finance New Grad Roles",
      "Product Management New Grad Roles",
    ],
    // speedyapply lists software roles only.
    speedyapply: false,
  },
  cs: {
    "simplify-internships": [
      "Software Engineering Internship Roles",
      "Data Science, AI & Machine Learning Internship Roles",
    ],
    "simplify-newgrad": [
      "Software Engineering New Grad Roles",
      "Data Science, AI & Machine Learning New Grad Roles",
    ],
  },
  engineering: {
    "simplify-internships": [
      "Hardware Engineering Internship Roles",
      "Software Engineering Internship Roles",
    ],
    "simplify-newgrad": [
      "Hardware Engineering New Grad Roles",
      "Software Engineering New Grad Roles",
    ],
  },
};

/** Job sources after choosing ``field``. Unknown sources and "other" are unchanged.
 * Business also gets an (empty) company watchlist to fill in the Apply settings, since
 * few finance and consulting postings reach the README lists. */
export function sourcesForField(sources: SourceConfig[], field: OnboardingField): SourceConfig[] {
  const preset = field ? FIELD_CATEGORIES[field] : undefined;
  if (!preset) return sources;
  const next = sources.map((source) => {
    const rule = preset[source.id];
    if (rule === undefined) return source;
    if (rule === false) return { ...source, enabled: false };
    return { ...source, categories: [...rule], enabled: true };
  });
  if (field === "business" && !next.some((source) => source.kind === "ats_board")) {
    next.push(newWatchlistSource());
  }
  return next;
}

export interface ResumeReview {
  entries: number;
  bullets: number;
  sections: { title: string; count: number }[];
  warnings: string[];
}

/** What the Review step shows about the imported master resume. */
export function reviewResume(resume: MasterResume | null): ResumeReview {
  const review: ResumeReview = { entries: 0, bullets: 0, sections: [], warnings: [] };
  if (!resume) return review;
  let untagged = 0;
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
        untagged += bullets.filter((b) => b.tags.length === 0).length;
        if (!dated) review.warnings.push(`No dates found for ${name || "an entry"}.`);
        if (bullets.length === 0) review.warnings.push(`${name || "An entry"} has no bullets.`);
      }
    } else if (section.kind === "list") {
      review.entries += section.entries.length;
    }
  }
  if (!resume.contact.name.trim() || resume.contact.name === "Your Name")
    review.warnings.unshift("Your name is missing.");
  if (untagged)
    review.warnings.push(
      `${untagged} bullet${untagged === 1 ? " has" : "s have"} no skill tags; untagged bullets rank lower for every job.`,
    );
  return review;
}

/** Whether a page load at ``pathname`` should go to the wizard first. */
export function needsWelcome(state: OnboardingState | null, pathname: string): boolean {
  if (!state || state.completed || state.skipped) return false;
  return !pathname.startsWith("/welcome") && !pathname.startsWith("/settings");
}
