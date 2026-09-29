import type { CatalogEntry, SourceCatalog, SourceConfig, SourceField, SourceKind } from "../api";

/** Most phrases one keyword search holds; the backend searches each one separately. */
export const MAX_PHRASES = 5;

/** The catalog entries "Restore defaults" re-adds (the sources every profile starts with). */
export const DEFAULT_CATALOG_IDS = ["simplify-internships", "simplify-newgrad", "speedyapply"];

/** Friendly labels for the catalog's field tags, in the order the pickers show them. */
export const FIELD_LABELS: Record<SourceField, string> = {
  swe: "Software engineering",
  data: "Data & machine learning",
  quant: "Quant",
  finance: "Finance",
  consulting: "Consulting",
  product: "Product management",
  business: "Business",
  hardware: "Hardware engineering",
  government: "Government",
};

export const SOURCE_FIELDS = Object.keys(FIELD_LABELS) as SourceField[];

const KIND_LABELS: Record<SourceKind, string> = {
  simplify_html: "Job list",
  pipe_table: "Job list",
  company_link_table: "Job list",
  ats_board: "Company watchlist",
  job_search: "Keyword search",
};

export function sourceKindLabel(kind: SourceKind): string {
  return KIND_LABELS[kind] ?? kind;
}

/** A README-backed source (the ones with categories to pick). */
export function isReadmeKind(kind: SourceKind): boolean {
  return kind === "simplify_html" || kind === "pipe_table" || kind === "company_link_table";
}

const PROVIDER_LABELS = { adzuna: "Adzuna", usajobs: "USAJobs" } as const;

/** What the list shows: the user's name, else a description of an unnamed legacy source. */
export function sourceDisplayName(source: SourceConfig): string {
  const name = source.name?.trim();
  if (name) return name;
  if (source.kind === "ats_board") return "Company watchlist";
  if (source.kind === "job_search") {
    const provider = source.provider ? PROVIDER_LABELS[source.provider] : "Job search";
    const phrases = splitPhrases(source.query ?? "");
    return phrases.length ? `${provider}: ${phrases.join(", ")}` : `${provider} search`;
  }
  return source.id;
}

/** "a, b ,, A" → ["a", "b"]: trimmed, no blanks, no case-insensitive repeats, at most 5. */
export function splitPhrases(query: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of query.split(",")) {
    const phrase = raw.trim();
    const key = phrase.toLowerCase();
    if (phrase && !seen.has(key)) {
      seen.add(key);
      out.push(phrase);
    }
  }
  return out.slice(0, MAX_PHRASES);
}

/** The stored form of a phrase list (`SourceConfig.query`). Commas inside a phrase are dropped. */
export function joinPhrases(phrases: string[]): string {
  return splitPhrases(phrases.map((p) => p.replace(/[,\s]+/g, " ")).join(",")).join(", ");
}

/** ``base``, or ``base-2``, ``base-3``… whichever no existing source uses. */
export function uniqueSourceId(base: string, sources: Pick<SourceConfig, "id">[]): string {
  const taken = new Set(sources.map((s) => s.id));
  const stem =
    base
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "source";
  if (!taken.has(stem)) return stem;
  let n = 2;
  while (taken.has(`${stem}-${n}`)) n += 1;
  return `${stem}-${n}`;
}

/** Whether ``entry`` is already among ``sources`` (by catalog id, or a legacy default's id). */
export function catalogAdded(entry: CatalogEntry, sources: SourceConfig[]): boolean {
  return sources.some(
    (s) => s.catalog_id === entry.id || (!s.catalog_id && s.id === entry.template.id),
  );
}

/** A copy of the entry's template ready to append, with a fresh id when its own is taken. */
export function sourceFromCatalog(entry: CatalogEntry, sources: SourceConfig[]): SourceConfig {
  const template = structuredClone(entry.template);
  return {
    ...template,
    id: uniqueSourceId(template.id || entry.id, sources),
    name: template.name || entry.name,
    enabled: true,
    catalog_id: entry.id,
    catalog_version: entry.version,
  };
}

/** Numeric-aware version order ("2027.10" > "2027.9"); negative when ``a`` is older. */
export function compareVersions(a: string, b: string): number {
  const parts = (v: string) => v.split(/[^0-9a-z]+/i).filter(Boolean);
  const left = parts(a);
  const right = parts(b);
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    const x = left[i] ?? "0";
    const y = right[i] ?? "0";
    const nx = Number(x);
    const ny = Number(y);
    const diff = Number.isFinite(nx) && Number.isFinite(ny) ? nx - ny : x.localeCompare(y);
    if (diff !== 0) return diff < 0 ? -1 : 1;
  }
  return 0;
}

/** The catalog entry with a newer version than the one ``source`` was added from, if any. */
export function availableUpdate(
  source: SourceConfig,
  catalog: SourceCatalog | null,
): CatalogEntry | null {
  if (!catalog || !source.catalog_id) return null;
  const entry = catalog.entries.find((e) => e.id === source.catalog_id);
  if (!entry) return null;
  if (!source.catalog_version) return entry;
  return compareVersions(source.catalog_version, entry.version) < 0 ? entry : null;
}

export type CatalogDiff = {
  url: { from: string; to: string } | null;
  added: string[];
  removed: string[];
};

/** What an update would change: the URL and the category list. */
export function catalogDiff(source: SourceConfig, entry: CatalogEntry): CatalogDiff {
  const next = entry.template;
  return {
    url: source.url !== next.url ? { from: source.url, to: next.url } : null,
    added: next.categories.filter((c) => !source.categories.includes(c)),
    removed: source.categories.filter((c) => !next.categories.includes(c)),
  };
}

/** ``source`` moved to ``entry``'s version; the id, name and on/off switch stay the user's. */
export function applyCatalogUpdate(source: SourceConfig, entry: CatalogEntry): SourceConfig {
  const next = entry.template;
  return {
    ...source,
    kind: next.kind,
    url: next.url,
    categories: [...next.categories],
    catalog_version: entry.version,
  };
}

/**
 * ``sources`` with every default catalog source that is missing appended. ``missing``
 * names defaults the catalog did not offer (nothing to restore them from).
 */
export function restoreDefaults(
  sources: SourceConfig[],
  catalog: SourceCatalog,
): { sources: SourceConfig[]; added: number; missing: string[] } {
  const out = [...sources];
  const missing: string[] = [];
  let added = 0;
  for (const id of DEFAULT_CATALOG_IDS) {
    const entry = catalog.entries.find((e) => e.id === id);
    if (!entry) missing.push(id);
    else if (!catalogAdded(entry, out)) {
      out.push(sourceFromCatalog(entry, out));
      added += 1;
    }
  }
  return { sources: out, added, missing };
}

/** Catalog entries tagged with any of ``fields``, in catalog order. */
export function entriesForFields(catalog: SourceCatalog, fields: SourceField[]): CatalogEntry[] {
  const wanted = new Set(fields);
  return catalog.entries.filter((entry) => entry.fields.some((f) => wanted.has(f)));
}

/** A new keyword search; it can only be saved once it has at least one phrase. */
export function newJobSearchSource(
  sources: SourceConfig[],
  fields: Partial<SourceConfig> = {},
): SourceConfig {
  return {
    id: uniqueSourceId("keyword-search", sources),
    kind: "job_search",
    name: "",
    url: "",
    categories: [],
    enabled: true,
    provider: "adzuna",
    query: "",
    location: "",
    country: "us",
    include: [],
    exclude: [],
    locations: [],
    max_age_days: 14,
    ...fields,
  };
}

/** A README source added by URL, with the format ``inspectSource`` detected. */
export function newReadmeSource(
  sources: SourceConfig[],
  url: string,
  kind: "simplify_html" | "pipe_table" | "company_link_table",
  name: string,
  categories: string[],
): SourceConfig {
  const base =
    name.trim() ||
    url
      .replace(/^https?:\/\/[^/]+\//, "")
      .split("/")
      .slice(0, 2)
      .join("-");
  return {
    id: uniqueSourceId(base || "job-list", sources),
    kind,
    name: name.trim(),
    url: url.trim(),
    categories: [...categories],
    enabled: true,
  };
}

/** Credentials each keyword-search provider needs (saved through `/api/secrets`). */
export const PROVIDER_KEYS: Record<"adzuna" | "usajobs", { name: string; label: string }[]> = {
  adzuna: [
    { name: "ADZUNA_APP_ID", label: "Adzuna app ID" },
    { name: "ADZUNA_APP_KEY", label: "Adzuna app key" },
  ],
  usajobs: [
    { name: "USAJOBS_API_KEY", label: "USAJobs API key" },
    { name: "USAJOBS_EMAIL", label: "USAJobs account email" },
  ],
};

/** "3 of 5 sources on". */
export function sourcesSummary(sources: SourceConfig[]): string {
  if (sources.length === 0) return "No sources yet";
  const on = sources.filter((s) => s.enabled).length;
  return `${on} of ${sources.length} source${sources.length === 1 ? "" : "s"} on`;
}
