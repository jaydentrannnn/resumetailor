import type { ApplySettings, SourceConfig, SourceFilters, WorkTypes } from "../api";

export const NO_FILTERS: SourceFilters = { include: [], exclude: [], locations: [] };

/** The profile's filters for every source; empty lists on settings from an older server. */
export function globalFiltersOf(apply: Pick<ApplySettings, "source_filters">): SourceFilters {
  return { ...NO_FILTERS, ...apply.source_filters };
}

/** "a, b" plus how many more: the first `shown` words of a list, or `empty` when none. */
export function shortList(words: string[], empty: string, shown = 2): string {
  if (!words.length) return empty;
  const more = words.length - shown;
  return words.slice(0, shown).join(", ") + (more > 0 ? ` +${more} more` : "");
}

export const ALL_WORK_TYPES: WorkTypes = { onsite: true, hybrid: true, remote: true };

/** Where postings may be, as one line ("On-site, Remote · United States, Vietnam only"). */
export function locationPolicySummary(filters: SourceFilters): string {
  const work = { ...ALL_WORK_TYPES, ...filters.work_types };
  const types = [work.onsite && "On-site", work.hybrid && "Hybrid", work.remote && "Remote"]
    .filter(Boolean)
    .join(", ");
  const countries = filters.countries?.length
    ? shortList(filters.countries, "")
    : "your work countries";
  const where =
    filters.other_countries === false ? `${countries} only` : `${countries} and elsewhere`;
  return `${types || "No work type"} · ${where}`;
}

/** What the eligibility switches and years limit skip, as one line ("Skips no sponsorship, …"). */
export function eligibilitySummary(
  apply: Pick<
    ApplySettings,
    | "exclude_no_sponsorship"
    | "exclude_citizenship_required"
    | "exclude_advanced_degree"
    | "eligibility"
  >,
): string {
  const skips = [
    apply.exclude_no_sponsorship && "no visa sponsorship",
    apply.exclude_citizenship_required && "citizenship required",
    apply.exclude_advanced_degree && "grad degree required",
    `${apply.eligibility.hard_reject_years}+ years' experience`,
  ].filter(Boolean);
  return `Skips ${skips.join(", ")}`;
}

/** A source's words with the global ones added, as the backend merges them before a fetch. */
export function effectiveFilters(source: SourceConfig, global: SourceFilters): SourceFilters {
  const merge = (a: string[], b: string[]) => {
    const seen = new Set<string>();
    return [...a, ...b].filter((w) => {
      const key = w.trim().toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };
  return {
    include: merge(source.ignore_global_include ? [] : global.include, source.include ?? []),
    exclude: merge(global.exclude, source.exclude ?? []),
    locations: merge(global.locations, source.locations ?? []),
  };
}

/** How many keep, skip and location words a source adds on top of the global ones. */
export function ownFilterCount(source: SourceConfig): number {
  return (
    (source.include?.length ?? 0) + (source.exclude?.length ?? 0) + (source.locations?.length ?? 0)
  );
}
