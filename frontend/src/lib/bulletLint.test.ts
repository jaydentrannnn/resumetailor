import { describe, expect, it } from "vitest";
import { firstVerb, lintBullet, suggestMissingTags } from "./bulletLint";

const codes = (text: string, tags: string[] = ["python"], opts = {}) =>
  lintBullet(text, tags, opts).map((hint) => hint.code);

describe("lintBullet", () => {
  it("is quiet for a strong, measured, tagged bullet", () => {
    expect(
      codes("Built a pricing model that cut churn 12%", ["python"], { charsPerLine: 90 }),
    ).toEqual([]);
  });

  it("flags weak openers, missing numbers and missing tags", () => {
    expect(codes("Responsible for the weekly report", [])).toEqual([
      "weak_verb",
      "no_metric",
      "no_tags",
    ]);
    expect(codes("Helped")).toContain("weak_verb");
    expect(codes("Helpedesk migration of 3 servers")).not.toContain("weak_verb");
  });

  it("flags bullets past two lines only when the line width is known", () => {
    const long = `Led ${"a".repeat(200)} 5`;
    expect(codes(long, ["x"], { charsPerLine: 90 })).toContain("too_long");
    expect(codes(long, ["x"])).not.toContain("too_long");
  });

  it("flags an opening verb repeated in the same entry", () => {
    expect(codes("Led 3 workshops", ["x"], { siblings: ["led the 5-person team"] })).toContain(
      "repeat_verb",
    );
    expect(firstVerb("• Analyzed, then")).toBe("analyzed");
  });

  it("ignores an empty bullet", () => {
    expect(lintBullet("   ", [])).toEqual([]);
  });
});

describe("suggestMissingTags", () => {
  it("finds vocabulary named in the text but not tagged", () => {
    const vocab = ["Python", "Go", "SQL"];
    const lower = new Set(vocab.map((t) => t.toLowerCase()));
    expect(
      suggestMissingTags("Queried SQL from google sheets in Python", ["python"], lower, vocab),
    ).toEqual(["SQL"]);
  });
});
