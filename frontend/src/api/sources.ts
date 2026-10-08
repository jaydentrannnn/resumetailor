/** Discovery sources: boards, watchlists, the source catalog, inspection and tests. */

import type { BoardAts, BoardConfig, SourceConfig } from "./applySettings";
import { request } from "./core";

// --- Discovery sources (P4-D) ---------------------------------------------------------

export type ResolvedBoard = BoardConfig & { jobs: number; url: string };

/** Check a careers link (or a board) against its ATS before it joins a watchlist. */
export function resolveBoard(
  input: { url: string } | { ats: BoardAts; slug: string; company?: string },
): Promise<ResolvedBoard> {
  return request<ResolvedBoard>("/api/apply/boards/resolve", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function fetchWatchlists(): Promise<Record<string, BoardConfig[]>> {
  return (await request<{ fields: Record<string, BoardConfig[]> }>("/api/apply/watchlists")).fields;
}

/** The category headings a README source offers. */
export async function fetchSourceSections(url: string): Promise<string[]> {
  return (
    await request<{ sections: string[] }>(
      `/api/apply/sources/sections?url=${encodeURIComponent(url)}`,
    )
  ).sections;
}

// --- Keyword-search presets (position x level x industry) -------------------------------

export type PresetChoice = { id: string; label: string };

export type SearchPresetChoices = {
  positions: PresetChoice[];
  levels: PresetChoice[];
  industries: (PresetChoice & { positions: string[] })[];
};

/** What a preset fills into a keyword search. */
export type SearchPresetBuild = { query: string; include: string[]; exclude: string[] };

export function fetchSearchPresets(): Promise<SearchPresetChoices> {
  return request<SearchPresetChoices>("/api/apply/search-presets");
}

export function buildSearchPreset(positions: string[], level: string): Promise<SearchPresetBuild> {
  const params = new URLSearchParams({ level });
  for (const position of positions) params.append("positions", position);
  return request<SearchPresetBuild>(`/api/apply/search-presets/build?${params.toString()}`);
}

// --- Source catalog, inspect and test (user-managed sources) ----------------------------

/** Field tags a catalog entry can carry; onboarding's field picker uses the same set. */
export type SourceField =
  | "swe"
  | "data"
  | "quant"
  | "finance"
  | "consulting"
  | "product"
  | "business"
  | "hardware"
  | "government";

/** How early-career a catalog list is; an entry may carry several (e.g. internships and new grad). */
export type SourceLevel = "intern" | "new_grad" | "off_cycle" | "program";

/** Finer focus inside a field: "banking" and "accounting" are both `finance`. */
export type SourceTrack =
  | "banking"
  | "markets"
  | "accounting"
  | "corp_finance"
  | "strategy"
  | "marketing"
  | "operations";

/** One curated source in the catalog. `template` is copied into `ApplySettings.sources`. */
export type CatalogEntry = {
  id: string;
  name: string;
  description: string;
  fields: SourceField[];
  /** Absent in catalogs written before levels existed. */
  levels?: SourceLevel[];
  tracks?: SourceTrack[];
  version: string;
  /** A ready-to-add source; `id` is regenerated if it collides with an existing source. */
  template: SourceConfig;
};

export type SourceCatalog = {
  schema_version: number;
  entries: CatalogEntry[];
  /** Where this copy came from: fetched now, the on-disk cache, or the app's bundled copy. */
  origin: "remote" | "cache" | "bundled";
};

export function fetchSourceCatalog(): Promise<SourceCatalog> {
  return request<SourceCatalog>("/api/apply/catalog");
}

export type SourceInspection = {
  /** The detected README format, or null when no parser found any rows. */
  kind: "simplify_html" | "pipe_table" | "company_link_table" | null;
  sections: string[];
  row_count: number;
};

/** Fetch a README URL once and detect its format and category headings. */
export function inspectSource(url: string): Promise<SourceInspection> {
  return request<SourceInspection>("/api/apply/sources/inspect", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

/** A subset of the backend's `sources.SourceRow`. */
export type SourceTestRow = {
  company: string;
  role: string;
  location: string;
  age: string;
  posted_at: string;
  application_link: string | null;
};

export type SourceTestResult = {
  /** Rows the source returned before the funnel's filters. */
  rows_total: number;
  /** Rows the daily funnel's filters would keep (ignoring what is already tracked). */
  rows_kept: number;
  sample: SourceTestRow[];
  errors: string[];
  /** Why rows fell out of `rows_total`: too_old, title, citizenship, advanced_degree, no_sponsorship. */
  dropped?: Record<string, number>;
  /** The posting-age limit the test applied, in days. */
  max_age_days?: number;
};

/** Run one source once without the funnel (no LLM, nothing saved). */
export function testSource(source: SourceConfig): Promise<SourceTestResult> {
  return request<SourceTestResult>("/api/apply/sources/test", {
    method: "POST",
    body: JSON.stringify({ source }),
  });
}

/** How one source did on its most recent run (daily run or Find jobs). */
export type SourceRunStatus = {
  /** Postings the source returned. */
  found: number;
  /** Postings the funnel's filters kept. */
  kept: number;
  /** Short reason the source failed or found nothing useful; null when fine. */
  error: string | null;
  /** ISO timestamp of that run. */
  at: string;
};

export type SourcesStatus = {
  /** Keyed by `SourceConfig.id`; a source that has never run is absent. */
  sources: Record<string, SourceRunStatus>;
  /** When the last run that touched sources finished; null before the first. */
  last_run_at: string | null;
};

/** Per-source results of the latest run, for the Sources tab's health line. */
export function fetchSourcesStatus(): Promise<SourcesStatus> {
  return request<SourcesStatus>("/api/apply/sources/status");
}
