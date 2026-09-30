import type {
  CatalogEntry,
  SourceCatalog,
  SourceConfig,
  SourceField,
  SourceKind,
  SourceRunStatus,
} from "../api";

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

export type SearchProvider = "adzuna" | "usajobs";

export const PROVIDER_LABELS: Record<SearchProvider, string> = {
  adzuna: "Adzuna",
  usajobs: "USAJobs",
};

/** The Sources tab's three groups; every source belongs to exactly one. */
export type SourceGroup = "lists" | "search" | "watchlists";

export function groupOf(kind: SourceKind): SourceGroup {
  if (kind === "job_search") return "search";
  if (kind === "ats_board") return "watchlists";
  return "lists";
}

/** The provider a keyword search runs on; older searches without one ran on Adzuna. */
export function providerOf(source: SourceConfig): SearchProvider {
  return source.provider === "usajobs" ? "usajobs" : "adzuna";
}

/** "owner/repo" from a GitHub link (also raw/blob READMEs); the host + path otherwise; "" when empty. */
export function repoNameFromUrl(url: string): string {
  const text = url.trim();
  if (!text) return "";
  const raw = text.match(/^https?:\/\/raw\.githubusercontent\.com\/([^/]+)\/([^/]+)/i);
  const hub = text.match(/^https?:\/\/(?:www\.)?github\.com\/([^/?#]+)\/([^/?#]+)/i);
  const hit = raw ?? hub;
  if (hit) return `${hit[1]}/${hit[2].replace(/\.git$/i, "")}`;
  return text.replace(/^https?:\/\/(www\.)?/i, "").replace(/[/?#].*$/, "") || text;
}

/** Company names on a watchlist (the board's slug when it has no name). */
function boardNames(source: SourceConfig): string[] {
  return (source.boards ?? []).map((b) => b.company?.trim() || b.slug);
}

/** "A, B, C +2": the first ``max`` of ``items``, then how many were left out. */
export function briefList(items: string[], max = 3): string {
  if (items.length <= max) return items.join(", ");
  return `${items.slice(0, max).join(", ")} +${items.length - max}`;
}

/** What the list shows: the user's name, else a description of an unnamed source (never a raw id). */
export function sourceDisplayName(source: SourceConfig): string {
  const name = source.name?.trim();
  if (name) return name;
  if (source.kind === "ats_board") {
    const names = boardNames(source);
    return names.length ? `Watchlist: ${briefList(names)}` : "Company watchlist";
  }
  if (source.kind === "job_search") {
    const provider = source.provider ? PROVIDER_LABELS[source.provider] : "Job search";
    const phrases = splitPhrases(source.query ?? "");
    return phrases.length ? `${provider}: ${phrases.join(", ")}` : `${provider} search`;
  }
  return repoNameFromUrl(source.url) || "Job list";
}

/** One line saying what a source looks at: categories, phrases or companies. */
export function sourceSummary(source: SourceConfig, maxChars = 90): string {
  let text: string;
  if (source.kind === "ats_board") {
    const names = boardNames(source);
    text = names.length ? names.join(", ") : "No companies yet";
  } else if (source.kind === "job_search") {
    const phrases = splitPhrases(source.query ?? "");
    const where = source.location?.trim();
    text = phrases.length ? phrases.join(", ") : "No search phrases yet";
    if (where) text += ` · ${where}`;
  } else {
    text = source.categories.length ? source.categories.join(", ") : "Every category";
  }
  return text.length > maxChars ? `${text.slice(0, maxChars - 1).trimEnd()}…` : text;
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

/** Catalog entries tagged with ``fields`` that ``sources`` does not have yet. */
export function recommendedEntries(
  catalog: SourceCatalog | null,
  sources: SourceConfig[],
  fields: SourceField[],
): CatalogEntry[] {
  if (!catalog || fields.length === 0) return [];
  return entriesForFields(catalog, fields).filter((entry) => !catalogAdded(entry, sources));
}

/** ``source`` as a separate copy right after the original (fresh id, no catalog link). */
export function duplicateSource(source: SourceConfig, sources: SourceConfig[]): SourceConfig[] {
  const copy: SourceConfig = {
    ...structuredClone(source),
    id: uniqueSourceId(source.id, sources),
    name: `${sourceDisplayName(source)} copy`,
    catalog_id: null,
    catalog_version: null,
  };
  const at = sources.findIndex((s) => s.id === source.id);
  const next = [...sources];
  next.splice(at < 0 ? next.length : at + 1, 0, copy);
  return next;
}

/** A removed source and where it sat, so Undo can put it back exactly. */
export type RemovedSource = { source: SourceConfig; index: number };

/** ``sources`` without the ``ids``, plus what was taken out (in list order). */
export function withoutSources(
  sources: SourceConfig[],
  ids: ReadonlySet<string>,
): { kept: SourceConfig[]; removed: RemovedSource[] } {
  const kept: SourceConfig[] = [];
  const removed: RemovedSource[] = [];
  sources.forEach((source, index) => {
    if (ids.has(source.id)) removed.push({ source, index });
    else kept.push(source);
  });
  return { kept, removed };
}

/** Puts ``removed`` back at their original positions (skipping any id that is present again). */
export function restoreRemoved(sources: SourceConfig[], removed: RemovedSource[]): SourceConfig[] {
  const out = [...sources];
  const have = new Set(out.map((s) => s.id));
  for (const { source, index } of [...removed].sort((a, b) => a.index - b.index)) {
    if (have.has(source.id)) continue;
    out.splice(Math.min(index, out.length), 0, source);
    have.add(source.id);
  }
  return out;
}

/** "5m ago", "2h ago", "3d ago"; "" when ``iso`` is not a date. */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export type SourceHealth = { text: string; tone: "ok" | "error" | "muted" };

/** The health line under a source: last run's counts, its failure reason, or why there is none. */
export function sourceHealth(
  source: SourceConfig,
  run: SourceRunStatus | undefined,
  now = Date.now(),
): SourceHealth {
  if (!source.enabled) return { text: "Off", tone: "muted" };
  if (!run) return { text: "Not run yet", tone: "muted" };
  const when = relativeTime(run.at, now);
  if (run.error) return { text: when ? `${run.error} · ${when}` : run.error, tone: "error" };
  const counts = `${run.found.toLocaleString("en-US")} found · ${run.kept.toLocaleString("en-US")} kept`;
  return { text: when ? `${counts} · ${when}` : counts, tone: "ok" };
}

/** "Searching 5 sources · last run 2h ago". */
export function sourcesHeadline(
  sources: SourceConfig[],
  lastRunAt: string | null | undefined,
  now = Date.now(),
): string {
  const on = sources.filter((s) => s.enabled).length;
  const when = relativeTime(lastRunAt, now);
  return `Searching ${on} source${on === 1 ? "" : "s"} · ${when ? `last run ${when}` : "not run yet"}`;
}
