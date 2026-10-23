import { describe, expect, it } from "vitest";
import type { CompanySource } from "../api";
import { hostOf, researchNotes, sourceLabel, splitAddition } from "./companyResearch";

const source = (patch: Partial<CompanySource>): CompanySource => ({
  id: "s1",
  kind: "site",
  url: null,
  title: "",
  fetched_at: "",
  sha: "",
  text: "",
  flags: [],
  ...patch,
});

describe("company research helpers", () => {
  it("names a page by its site and other sources by their kind", () => {
    expect(sourceLabel(source({ url: "https://www.acme.example/about" }))).toBe("acme.example");
    expect(sourceLabel(source({ kind: "posting" }))).toBe("Job posting");
    expect(sourceLabel(source({ kind: "note" }))).toBe("Your note");
    expect(sourceLabel(undefined)).toBe("Unknown source");
    expect(hostOf("not a url")).toBe("");
  });

  it("reads one link as a page and anything else as a note", () => {
    expect(splitAddition(" https://acme.example/team ")).toEqual({
      urls: ["https://acme.example/team"],
      notes: [],
    });
    expect(splitAddition("acme.example")).toEqual({ urls: ["acme.example"], notes: [] });
    expect(splitAddition("Met their recruiter. They use acme.example")).toEqual({
      urls: [],
      notes: ["Met their recruiter. They use acme.example"],
    });
    expect(splitAddition("  ")).toEqual({ urls: [], notes: [] });
  });

  it("says how many facts the check left out", () => {
    const base = {
      company: "Acme",
      researched_at: "",
      sources: [],
      facts: [],
      removed: [],
      searched_with: "",
      model: "",
    };
    expect(researchNotes({ ...base, dropped: 1, warnings: ["W"] })).toEqual([
      "W",
      "1 fact was left out: the quoted words were not in the source.",
    ]);
    expect(researchNotes({ ...base, dropped: 0, warnings: [] })).toEqual([]);
  });
});
