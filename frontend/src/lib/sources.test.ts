import { describe, expect, it } from "vitest";
import type { CatalogEntry, SourceCatalog, SourceConfig } from "../api";
import {
  applyCatalogUpdate,
  availableUpdate,
  catalogAdded,
  catalogDiff,
  compareVersions,
  duplicateSource,
  groupOf,
  joinPhrases,
  recommendedEntries,
  relativeTime,
  repoNameFromUrl,
  restoreDefaults,
  restoreRemoved,
  sourceDisplayName,
  sourceFromCatalog,
  sourceHealth,
  sourcesHeadline,
  sourceSummary,
  splitPhrases,
  uniqueSourceId,
  withoutSources,
} from "./sources";

const entry = (over: Partial<CatalogEntry> & { id: string }): CatalogEntry => ({
  name: over.id,
  description: "",
  fields: ["swe"],
  version: "1",
  template: {
    id: over.id,
    kind: "simplify_html",
    url: `https://x/${over.id}`,
    categories: ["A"],
    enabled: true,
  },
  ...over,
});

const catalog = (entries: CatalogEntry[]): SourceCatalog => ({
  schema_version: 1,
  entries,
  origin: "bundled",
});

describe("phrases", () => {
  it("splits, trims, dedupes and caps at five", () => {
    expect(splitPhrases(" a, b ,, A ,c,d,e,f")).toEqual(["a", "b", "c", "d", "e"]);
    expect(splitPhrases("")).toEqual([]);
  });

  it("joins with commas and strips commas inside a phrase", () => {
    expect(joinPhrases(["data analyst", "risk, credit"])).toBe("data analyst, risk credit");
    expect(joinPhrases(["1", "2", "3", "4", "5", "6"])).toBe("1, 2, 3, 4, 5");
  });
});

describe("catalog helpers", () => {
  it("regenerates the id on collision and records the catalog origin", () => {
    const e = entry({ id: "simplify-internships", version: "3", name: "Simplify" });
    const taken: SourceConfig[] = [
      {
        id: "simplify-internships",
        kind: "simplify_html",
        url: "u",
        categories: [],
        enabled: true,
      },
    ];
    const made = sourceFromCatalog(e, taken);
    expect(made.id).toBe("simplify-internships-2");
    expect(made).toMatchObject({ catalog_id: "simplify-internships", catalog_version: "3" });
    expect(made.name).toBe("Simplify");
    expect(uniqueSourceId("company-watchlist", [])).toBe("company-watchlist");
  });

  it("treats a legacy default with the same id as already added", () => {
    const e = entry({ id: "speedyapply" });
    expect(
      catalogAdded(e, [
        { id: "speedyapply", kind: "pipe_table", url: "u", categories: [], enabled: true },
      ]),
    ).toBe(true);
    expect(catalogAdded(e, [])).toBe(false);
  });

  it("orders versions numerically", () => {
    expect(compareVersions("2027.9", "2027.10")).toBeLessThan(0);
    expect(compareVersions("2", "2")).toBe(0);
    expect(compareVersions("3", "2")).toBeGreaterThan(0);
  });

  it("offers an update only for a newer catalog version, and diffs it", () => {
    const newer = entry({
      id: "a",
      version: "2",
      template: {
        id: "a",
        kind: "simplify_html",
        url: "new",
        categories: ["A", "B"],
        enabled: true,
      },
    });
    const source: SourceConfig = {
      id: "a",
      kind: "simplify_html",
      url: "old",
      categories: ["A", "Z"],
      enabled: true,
      catalog_id: "a",
      catalog_version: "1",
    };
    expect(availableUpdate(source, catalog([newer]))).toBe(newer);
    expect(availableUpdate({ ...source, catalog_version: "2" }, catalog([newer]))).toBeNull();
    expect(availableUpdate({ ...source, catalog_id: null }, catalog([newer]))).toBeNull();
    expect(catalogDiff(source, newer)).toEqual({
      url: { from: "old", to: "new" },
      added: ["B"],
      removed: ["Z"],
    });
    expect(applyCatalogUpdate({ ...source, enabled: false, name: "Mine" }, newer)).toMatchObject({
      url: "new",
      categories: ["A", "B"],
      catalog_version: "2",
      enabled: false,
      name: "Mine",
    });
  });

  it("restores only the missing defaults", () => {
    const cat = catalog(
      ["simplify-internships", "simplify-newgrad", "speedyapply"].map((id) => entry({ id })),
    );
    const have: SourceConfig[] = [
      { id: "speedyapply", kind: "pipe_table", url: "u", categories: [], enabled: true },
    ];
    const out = restoreDefaults(have, cat);
    expect(out.added).toBe(2);
    expect(out.sources.map((s) => s.id)).toEqual([
      "speedyapply",
      "simplify-internships",
      "simplify-newgrad",
    ]);
    expect(restoreDefaults(out.sources, cat).added).toBe(0);
    expect(restoreDefaults([], catalog([])).missing).toHaveLength(3);
  });

  it("names unnamed sources sensibly", () => {
    expect(
      sourceDisplayName({
        id: "s",
        kind: "job_search",
        url: "",
        categories: [],
        enabled: true,
        provider: "adzuna",
        query: "a, b",
      }),
    ).toBe("Adzuna: a, b");
    expect(
      sourceDisplayName({
        id: "x",
        name: " Mine ",
        kind: "pipe_table",
        url: "",
        categories: [],
        enabled: true,
      }),
    ).toBe("Mine");
  });
});

const base = (over: Partial<SourceConfig> & { id: string }): SourceConfig => ({
  kind: "simplify_html",
  url: "",
  categories: [],
  enabled: true,
  ...over,
});

describe("groups and names", () => {
  it("puts each kind in one group", () => {
    expect(groupOf("simplify_html")).toBe("lists");
    expect(groupOf("pipe_table")).toBe("lists");
    expect(groupOf("company_link_table")).toBe("lists");
    expect(groupOf("job_search")).toBe("search");
    expect(groupOf("ats_board")).toBe("watchlists");
  });

  it("derives a friendly name from the link, phrases or companies, never the id", () => {
    expect(repoNameFromUrl("https://github.com/SimplifyJobs/Summer2026-Internships")).toBe(
      "SimplifyJobs/Summer2026-Internships",
    );
    expect(repoNameFromUrl("https://github.com/o/r/blob/dev/README.md")).toBe("o/r");
    expect(repoNameFromUrl("https://raw.githubusercontent.com/o/r/dev/README.md")).toBe("o/r");
    expect(repoNameFromUrl("https://example.com/jobs?x=1")).toBe("example.com");
    expect(sourceDisplayName(base({ id: "raw-id", url: "https://github.com/o/r" }))).toBe("o/r");
    expect(sourceDisplayName(base({ id: "raw-id" }))).toBe("Job list");
    expect(
      sourceDisplayName(
        base({
          id: "w",
          kind: "ats_board",
          boards: [
            { ats: "greenhouse", slug: "a", company: "Acme" },
            { ats: "lever", slug: "b", company: "" },
            { ats: "ashby", slug: "c", company: "Cee" },
            { ats: "ashby", slug: "d", company: "Dee" },
          ],
        }),
      ),
    ).toBe("Watchlist: Acme, b, Cee +1");
    expect(sourceDisplayName(base({ id: "w", kind: "ats_board" }))).toBe("Company watchlist");
  });

  it("summarises what a source looks at on one line", () => {
    expect(sourceSummary(base({ id: "a", categories: ["SWE", "Data"] }))).toBe("SWE, Data");
    expect(sourceSummary(base({ id: "a" }))).toBe("Every category");
    expect(
      sourceSummary(base({ id: "s", kind: "job_search", query: "a, b", location: "NYC" })),
    ).toBe("a, b · NYC");
    expect(sourceSummary(base({ id: "w", kind: "ats_board" }))).toBe("No companies yet");
    expect(sourceSummary(base({ id: "a", categories: ["x".repeat(200)] }), 20)).toHaveLength(20);
  });
});

describe("health", () => {
  const NOW = Date.parse("2026-09-29T12:00:00Z");
  const source = base({ id: "a" });

  it("formats relative times", () => {
    expect(relativeTime("2026-09-29T11:59:50Z", NOW)).toBe("just now");
    expect(relativeTime("2026-09-29T11:15:00Z", NOW)).toBe("45m ago");
    expect(relativeTime("2026-09-29T10:00:00Z", NOW)).toBe("2h ago");
    expect(relativeTime("2026-09-26T12:00:00Z", NOW)).toBe("3d ago");
    expect(relativeTime("nonsense", NOW)).toBe("");
    expect(relativeTime(null, NOW)).toBe("");
  });

  it("reports ok, error, never-run and off", () => {
    const run = { found: 1412, kept: 20, error: null, at: "2026-09-29T10:00:00Z" };
    expect(sourceHealth(source, run, NOW)).toEqual({
      text: "1,412 found · 20 kept · 2h ago",
      tone: "ok",
    });
    expect(
      sourceHealth(source, { ...run, found: 0, kept: 0, error: "needs ADZUNA_APP_KEY" }, NOW),
    ).toEqual({ text: "needs ADZUNA_APP_KEY · 2h ago", tone: "error" });
    expect(sourceHealth(source, undefined, NOW)).toEqual({ text: "Not run yet", tone: "muted" });
    expect(sourceHealth({ ...source, enabled: false }, run, NOW)).toEqual({
      text: "Off",
      tone: "muted",
    });
  });

  it("writes the header line", () => {
    const list = [source, base({ id: "b", enabled: false }), base({ id: "c" })];
    expect(sourcesHeadline(list, "2026-09-29T10:00:00Z", NOW)).toBe(
      "Searching 2 sources · last run 2h ago",
    );
    expect(sourcesHeadline([source], null, NOW)).toBe("Searching 1 source · not run yet");
  });
});

describe("editing the list", () => {
  const a = base({ id: "a" });
  const b = base({ id: "b" });
  const c = base({ id: "c" });

  it("removes and restores at the original positions", () => {
    const { kept, removed } = withoutSources([a, b, c], new Set(["a", "c"]));
    expect(kept).toEqual([b]);
    expect(restoreRemoved(kept, removed)).toEqual([a, b, c]);
    // An id that came back some other way is not duplicated.
    expect(restoreRemoved([a, b], removed).map((s) => s.id)).toEqual(["a", "b", "c"]);
  });

  it("duplicates right after the original, unlinked from the catalog", () => {
    const linked = base({ id: "a", name: "Mine", catalog_id: "x", catalog_version: "1" });
    const out = duplicateSource(linked, [linked, b]);
    expect(out.map((s) => s.id)).toEqual(["a", "a-2", "b"]);
    expect(out[1]).toMatchObject({ name: "Mine copy", catalog_id: null });
  });

  it("recommends catalog entries for the fields that are not added yet", () => {
    const cat = catalog([
      entry({ id: "fin", fields: ["finance"] }),
      entry({ id: "swe", fields: ["swe"] }),
      entry({ id: "fin2", fields: ["finance", "quant"] }),
    ]);
    const have = [base({ id: "fin2", catalog_id: "fin2" })];
    expect(recommendedEntries(cat, have, ["finance"]).map((e) => e.id)).toEqual(["fin"]);
    expect(recommendedEntries(cat, have, [])).toEqual([]);
    expect(recommendedEntries(null, have, ["finance"])).toEqual([]);
  });
});
