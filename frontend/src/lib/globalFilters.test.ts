import { describe, expect, it } from "vitest";
import type { SourceConfig } from "../api";
import {
  effectiveFilters,
  eligibilitySummary,
  globalFiltersOf,
  ownFilterCount,
  shortList,
} from "./globalFilters";

const source = (extra: Partial<SourceConfig> = {}): SourceConfig => ({
  id: "s",
  kind: "ats_board",
  url: "",
  categories: [],
  enabled: true,
  ...extra,
});

describe("globalFilters", () => {
  it("fills in empty lists for settings from an older server", () => {
    expect(globalFiltersOf({})).toEqual({ include: [], exclude: [], locations: [] });
  });

  it("shortens long lists", () => {
    expect(shortList([], "Any title")).toBe("Any title");
    expect(shortList(["a", "b"], "")).toBe("a, b");
    expect(shortList(["a", "b", "c", "d"], "")).toBe("a, b +2 more");
  });

  it("adds a source's words after the global ones, dropping repeats", () => {
    const global = { include: ["Analyst"], exclude: ["senior"], locations: ["Remote"] };
    const merged = effectiveFilters(
      source({ include: ["analyst", "associate"], exclude: ["ops"] }),
      global,
    );
    expect(merged).toEqual({
      include: ["Analyst", "associate"],
      exclude: ["senior", "ops"],
      locations: ["Remote"],
    });
    expect(effectiveFilters(source({ ignore_global_include: true }), global).include).toEqual([]);
  });

  it("counts only the source's own words", () => {
    expect(ownFilterCount(source({ max_age_days: 7 }))).toBe(0);
    expect(ownFilterCount(source({ include: ["a"], locations: ["b", "c"] }))).toBe(3);
  });

  it("summarises eligibility", () => {
    expect(
      eligibilitySummary({
        exclude_no_sponsorship: true,
        exclude_citizenship_required: false,
        exclude_advanced_degree: true,
        eligibility: {
          hard_reject_years: 4,
          flag_years: 2,
          extra_title_block: [],
          extra_text_block: [],
        },
      }),
    ).toBe("Skips no visa sponsorship, grad degree required, 4+ years' experience");
  });
});
