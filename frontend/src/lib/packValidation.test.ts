import { describe, expect, it } from "vitest";
import {
  errorsFor,
  normalizeVerb,
  slugify,
  validatePackDraft,
  verbTokenError,
  type PackDraftForValidation,
} from "./packValidation";

function draft(overrides: Partial<PackDraftForValidation> = {}): PackDraftForValidation {
  return {
    label: "Test Pack",
    tag_aliases: {},
    verb_families: {},
    ...overrides,
  };
}

describe("validatePackDraft — parity with libraries.py::validate_pack", () => {
  it("returns no errors for a clean draft", () => {
    expect(
      validatePackDraft(
        draft({ tag_aliases: { py: "python" }, verb_families: { build: ["led"] } }),
      ),
    ).toEqual([]);
  });

  it("rejects an empty label (libraries.py:704)", () => {
    const errors = validatePackDraft(draft({ label: "   " }));
    expect(errors).toEqual([{ field: { kind: "label" }, message: expect.any(String) }]);
  });

  it("an empty alias key yields only the non-empty error, not a chain error too (libraries.py:714, continue)", () => {
    const errors = validatePackDraft(draft({ tag_aliases: { "": "python" } }));
    expect(errors).toHaveLength(1);
    expect(errors[0].message).toMatch(/non-empty/);
  });

  it("an empty alias value also fails (libraries.py:714)", () => {
    const errors = validatePackDraft(draft({ tag_aliases: { python: "" } }));
    expect(errors).toHaveLength(1);
    expect(errors[0].message).toMatch(/non-empty/);
  });

  it("a self-alias yields only the self-alias error, not a chain error (libraries.py:719, continue)", () => {
    const errors = validatePackDraft(draft({ tag_aliases: { python: "python" } }));
    expect(errors).toHaveLength(1);
    expect(errors[0].message).toMatch(/maps to itself/);
  });

  it("self-alias check normalizes both sides (libraries.py:713)", () => {
    const errors = validatePackDraft(draft({ tag_aliases: { "  Python  ": "python" } }));
    expect(errors.some((e) => e.message.includes("maps to itself"))).toBe(true);
  });

  it("an over-length self-alias yields TWO errors — no continue on the length check (libraries.py:717-718)", () => {
    const long = "a".repeat(121);
    const errors = validatePackDraft(draft({ tag_aliases: { [long]: long.toUpperCase() } }));
    expect(errors).toHaveLength(2);
    expect(errors.some((e) => e.message.includes("exceeds"))).toBe(true);
    expect(errors.some((e) => e.message.includes("maps to itself"))).toBe(true);
  });

  it("length is measured on the normalized (stripped) string (libraries.py:717)", () => {
    const key = "  " + "a".repeat(120) + "  "; // normalizes to exactly 120 chars
    const errors = validatePackDraft(draft({ tag_aliases: { [key]: "python" } }));
    expect(errors).toEqual([]);
  });

  it("detects an in-pack chain, locating the error on the chaining key (libraries.py:722)", () => {
    const errors = validatePackDraft(draft({ tag_aliases: { x: "y", y: "z" } }));
    expect(errors).toHaveLength(1);
    expect(errors[0].field).toEqual({ kind: "alias", key: "x" });
    expect(errors[0].message).toMatch(/chains/);
  });

  it("chain detection is normalization-aware but the locator keeps the raw key (libraries.py:711)", () => {
    const errors = validatePackDraft(draft({ tag_aliases: { X: "y", y: "z" } }));
    expect(errors).toHaveLength(1);
    expect(errors[0].field).toEqual({ kind: "alias", key: "X" });
  });

  it("caps total aliases at 2000 (libraries.py:708)", () => {
    const many: Record<string, string> = {};
    for (let i = 0; i < 2001; i++) many[`k${i}`] = `v${i}`;
    const errors = validatePackDraft(draft({ tag_aliases: many }));
    expect(errors.some((e) => e.field.kind === "aliases")).toBe(true);
  });

  it("exactly 2000 aliases is fine", () => {
    const many: Record<string, string> = {};
    for (let i = 0; i < 2000; i++) many[`k${i}`] = `v${i}`;
    const errors = validatePackDraft(draft({ tag_aliases: many }));
    expect(errors.some((e) => e.field.kind === "aliases")).toBe(false);
  });

  it("rejects a family name that slugifies to empty (libraries.py:749)", () => {
    for (const bad of ["★★", "護理", "   "]) {
      const errors = validatePackDraft(draft({ verb_families: { [bad]: ["led"] } }));
      expect(
        errors.some((e) => e.field.kind === "family" && e.message.includes("Invalid family")),
      ).toBe(true);
    }
  });

  it("accepts a family name with real content, including accents (libraries.py:749)", () => {
    for (const ok of ["Care Delivery", "café"]) {
      const errors = validatePackDraft(draft({ verb_families: { [ok]: ["led"] } }));
      expect(errors).toEqual([]);
    }
  });

  it("caps families at 60 (libraries.py:745)", () => {
    const many: Record<string, string[]> = {};
    for (let i = 0; i < 61; i++) many[`family${i}`] = ["led"];
    const errors = validatePackDraft(draft({ verb_families: many }));
    expect(errors.some((e) => e.field.kind === "families")).toBe(true);
  });

  it("exactly 60 families is fine", () => {
    const many: Record<string, string[]> = {};
    for (let i = 0; i < 60; i++) many[`family${i}`] = ["led"];
    const errors = validatePackDraft(draft({ verb_families: many }));
    expect(errors.some((e) => e.field.kind === "families")).toBe(false);
  });

  it("caps verbs per family at 500, counted before dedupe (libraries.py:751)", () => {
    const verbs = Array.from({ length: 501 }, () => "led");
    const errors = validatePackDraft(draft({ verb_families: { build: verbs } }));
    expect(
      errors.some((e) => e.field.kind === "family" && e.message.includes("too many verbs")),
    ).toBe(true);
  });

  it("exactly 500 verbs in a family is fine", () => {
    const verbs = Array.from({ length: 500 }, (_, i) => `verb${i}`);
    const errors = validatePackDraft(draft({ verb_families: { build: verbs } }));
    expect(
      errors.some((e) => e.field.kind === "family" && e.message.includes("too many verbs")),
    ).toBe(false);
  });

  it("rejects non-alphabetic verbs (libraries.py:758)", () => {
    for (const bad of ["re-factored", "follow up", "e2e", "led3"]) {
      const errors = validatePackDraft(draft({ verb_families: { build: [bad] } }));
      expect(errors.some((e) => e.message.includes("must be alphabetic"))).toBe(true);
    }
  });

  it("accepts Unicode alphabetic verbs — a stricter ASCII-only check would wrongly reject these", () => {
    for (const ok of ["café", "führte"]) {
      const errors = validatePackDraft(draft({ verb_families: { build: [ok] } }));
      expect(errors).toEqual([]);
    }
  });

  it("verb check strips and lowercases before testing (libraries.py:757)", () => {
    const errors = validatePackDraft(draft({ verb_families: { build: ["  Administered "] } }));
    expect(errors).toEqual([]);
  });

  it("rejects the same verb claimed by two families (libraries.py:763)", () => {
    const errors = validatePackDraft(draft({ verb_families: { build: ["led"], lead: ["led"] } }));
    expect(errors).toHaveLength(1);
    expect(errors[0].message).toMatch(/both/);
  });

  it("does not flag the same verb repeated within one family", () => {
    const errors = validatePackDraft(draft({ verb_families: { build: ["led", "led"] } }));
    expect(errors).toEqual([]);
  });

  it("families differing only by case still collide (libraries.py:763 compares raw, case-sensitive)", () => {
    const errors = validatePackDraft(draft({ verb_families: { Care: ["led"], care: ["led"] } }));
    expect(errors).toHaveLength(1);
    expect(errors[0].message).toContain("Care");
    expect(errors[0].message).toContain("care");
  });

  it("three families sharing one verb produce exactly two errors, chained pairwise (libraries.py:768, unconditional overwrite)", () => {
    const errors = validatePackDraft(
      draft({ verb_families: { f1: ["led"], f2: ["led"], f3: ["led"] } }),
    );
    expect(errors).toHaveLength(2);
    expect(errors[0].message).toMatch(/f1.*f2|f2.*f1/);
    expect(errors[1].message).toMatch(/f2.*f3|f3.*f2/);
  });

  it("a non-alphabetic verb never also triggers the duplicate-family check (libraries.py:762, continue)", () => {
    const errors = validatePackDraft(
      draft({ verb_families: { build: ["re-factored"], lead: ["re-factored"] } }),
    );
    expect(errors).toHaveLength(2);
    expect(errors.every((e) => e.message.includes("must be alphabetic"))).toBe(true);
  });

  it("rejects a named family with zero verbs — client-only UX safeguard, not a libraries.py rule", () => {
    const errors = validatePackDraft(draft({ verb_families: { care: [] } }));
    expect(errors).toHaveLength(1);
    expect(errors[0].field).toEqual({ kind: "family", family: "care" });
    expect(errors[0].message).toMatch(/at least one verb/);
  });

  it("boundary: cross-pack chains are NOT checked client-side (libraries.py:727-736 needs the effective table)", () => {
    // "ml" -> "machine learning" already exists in core-tech; neither direction is
    // client-checkable without the composed effective table, so both must pass here.
    expect(validatePackDraft(draft({ tag_aliases: { foo: "ml" } }))).toEqual([]);
    expect(validatePackDraft(draft({ tag_aliases: { "machine learning": "ml" } }))).toEqual([]);
  });
});

describe("normalizeVerb", () => {
  it("trims and lowercases", () => {
    expect(normalizeVerb("  Administered  ")).toBe("administered");
  });
});

describe("verbTokenError", () => {
  it("accepts an alphabetic verb", () => {
    expect(verbTokenError("administered")).toBeNull();
  });

  it("rejects a non-alphabetic verb", () => {
    expect(verbTokenError("re-factored")).not.toBeNull();
  });

  it("rejects an empty verb", () => {
    expect(verbTokenError("")).not.toBeNull();
  });
});

describe("slugify — mirrors config.py's slugify exactly", () => {
  it("lowercases and hyphenates", () => {
    expect(slugify("Care Delivery")).toBe("care-delivery");
  });

  it("strips leading/trailing hyphens", () => {
    expect(slugify("  Care!!  ")).toBe("care");
  });

  it("truncates to 40 characters", () => {
    expect(slugify("a".repeat(50)).length).toBe(40);
  });

  it("produces empty output for names with no [a-z0-9] characters", () => {
    expect(slugify("★★")).toBe("");
    expect(slugify("   ")).toBe("");
  });
});

describe("errorsFor", () => {
  it("looks up errors by locator", () => {
    const errors = validatePackDraft(draft({ tag_aliases: { python: "python" } }));
    expect(errorsFor(errors, { kind: "alias", key: "python" })).toHaveLength(1);
    expect(errorsFor(errors, { kind: "alias", key: "other" })).toHaveLength(0);
  });
});
