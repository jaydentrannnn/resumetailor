import { describe, expect, it } from "vitest";
import { firstVerb, lintBullet } from "./bulletLint";

const codes = (text: string, opts = {}) => lintBullet(text, opts).map((hint) => hint.code);

describe("lintBullet", () => {
  it("is quiet for a strong, measured bullet", () => {
    expect(codes("Built a pricing model that cut churn 12%", { charsPerLine: 90 })).toEqual([]);
  });

  it("flags weak openers and missing numbers, never missing skills", () => {
    expect(codes("Responsible for the weekly report")).toEqual(["weak_verb", "no_metric"]);
    expect(codes("Helped")).toContain("weak_verb");
    expect(codes("Helpedesk migration of 3 servers")).not.toContain("weak_verb");
  });

  it("flags bullets past two lines only when the line width is known", () => {
    const long = `Led ${"a".repeat(200)} 5`;
    expect(codes(long, { charsPerLine: 90 })).toContain("too_long");
    expect(codes(long)).not.toContain("too_long");
  });

  it("flags an opening verb repeated in the same entry", () => {
    expect(codes("Led 3 workshops", { siblings: ["led the 5-person team"] })).toContain(
      "repeat_verb",
    );
    expect(firstVerb("• Analyzed, then")).toBe("analyzed");
  });

  it("ignores an empty bullet", () => {
    expect(lintBullet("   ")).toEqual([]);
  });
});
