import { describe, expect, it } from "vitest";
import type { CatalogEntry, SourceCatalog, SourceConfig } from "../api";
import {
  applyCatalogUpdate,
  availableUpdate,
  catalogAdded,
  catalogDiff,
  compareVersions,
  joinPhrases,
  restoreDefaults,
  sourceDisplayName,
  sourceFromCatalog,
  splitPhrases,
  uniqueSourceId,
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
