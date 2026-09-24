/**
 * Client-side mirror of the subset of `libraries.py::validate_pack` that needs no
 * server state — lets the pack editor mark bad rows inline instead of round-tripping
 * to a 400. Deliberately absent: cross-pack alias chains and the existing-target
 * overwrite check (libraries.py:727-742), both of which read the composed effective
 * table across every enabled pack. A clean result here does NOT mean the write will
 * succeed — the server's `errors` array stays authoritative for those two rules.
 */

/** Mirrors libraries.py:683-686. */
export const PACK_LIMITS = {
  maxAliases: 2000,
  maxAliasLen: 120,
  maxFamilies: 60,
  maxVerbsPerFamily: 500,
} as const;

export type PackFieldRef =
  | { kind: "label" }
  | { kind: "aliases" }
  | { kind: "alias"; key: string }
  | { kind: "families" }
  | { kind: "family"; family: string }
  | { kind: "verb"; family: string; verb: string };

export type PackValidationError = { field: PackFieldRef; message: string };

export type PackDraftForValidation = {
  label: string;
  tag_aliases: Record<string, string>;
  verb_families: Record<string, string[]>;
};

/** `t.trim().toLowerCase()` — shared so a chip always reads exactly as it will be
 * saved (libraries.py normalizes the same way before every check). */
export function normalizeVerb(token: string): string {
  return token.trim().toLowerCase();
}

/** Unicode-aware, mirroring Python's `str.isalpha()` — `/^[a-z]+$/` would reject
 * "café"/"führte" and be stricter than the server. Expects an already-normalized verb. */
const ALPHA = /^\p{L}+$/u;

/** Mirrors libraries.py:758. Returns null when the verb is acceptable. */
export function verbTokenError(verb: string): string | null {
  if (!verb || !ALPHA.test(verb)) {
    return `"${verb}" must be alphabetic.`;
  }
  return null;
}

/** Mirrors config.py's `slugify` exactly (config.py:1113-1120) — used only to check
 * whether a family name would slugify to nothing. */
export function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "")
    .replace(/-+$/, "")
    .slice(0, 40);
}

export function errorsFor(errors: PackValidationError[], ref: PackFieldRef): string[] {
  return errors.filter((e) => sameRef(e.field, ref)).map((e) => e.message);
}

function sameRef(a: PackFieldRef, b: PackFieldRef): boolean {
  if (a.kind !== b.kind) return false;
  switch (a.kind) {
    case "alias":
      return b.kind === "alias" && a.key === b.key;
    case "family":
      return b.kind === "family" && a.family === b.family;
    case "verb":
      return b.kind === "verb" && a.family === b.family && a.verb === b.verb;
    default:
      return true;
  }
}

/**
 * Every `validate_pack` rule that needs no server state. Mirrors the source's control
 * flow exactly, including its `continue`s — see libraries.py:689-770. Order and
 * short-circuiting matter for parity: e.g. an empty alias yields only the "non-empty"
 * error, never a chain error too, because the server `continue`s past it.
 */
export function validatePackDraft(draft: PackDraftForValidation): PackValidationError[] {
  const errors: PackValidationError[] = [];

  if (!draft.label.trim()) {
    errors.push({ field: { kind: "label" }, message: "Label cannot be empty." });
  }

  const aliasEntries = Object.entries(draft.tag_aliases);
  if (aliasEntries.length > PACK_LIMITS.maxAliases) {
    errors.push({
      field: { kind: "aliases" },
      message: `Too many aliases (${aliasEntries.length} > ${PACK_LIMITS.maxAliases}).`,
    });
  }

  const packKeys = new Set(aliasEntries.map(([rawK]) => rawK.trim().toLowerCase()));
  for (const [rawK, rawV] of aliasEntries) {
    const k = rawK.trim().toLowerCase();
    const v = rawV.trim().toLowerCase();
    const ref: PackFieldRef = { kind: "alias", key: rawK };
    if (!k || !v) {
      errors.push({
        field: ref,
        message: `"${rawK}" → "${rawV}": key and value must be non-empty.`,
      });
      continue;
    }
    if (k.length > PACK_LIMITS.maxAliasLen || v.length > PACK_LIMITS.maxAliasLen) {
      errors.push({
        field: ref,
        message: `"${rawK}" → "${rawV}" exceeds ${PACK_LIMITS.maxAliasLen} characters.`,
      });
    }
    if (k === v) {
      errors.push({ field: ref, message: `"${rawK}" maps to itself.` });
      continue;
    }
    if (packKeys.has(v)) {
      errors.push({
        field: ref,
        message: `"${rawK}" → "${rawV}" chains: "${rawV}" is itself an alias key in this pack.`,
      });
    }
  }

  const familyEntries = Object.entries(draft.verb_families);
  if (familyEntries.length > PACK_LIMITS.maxFamilies) {
    errors.push({
      field: { kind: "families" },
      message: `Too many verb families (${familyEntries.length} > ${PACK_LIMITS.maxFamilies}).`,
    });
  }

  const seenVerbs = new Map<string, string>(); // normalized verb -> raw family (last wins)
  for (const [family, verbs] of familyEntries) {
    const familyRef: PackFieldRef = { kind: "family", family };
    if (!slugify(family)) {
      errors.push({ field: familyRef, message: `Invalid family name "${family}".` });
    }
    if (verbs.length > PACK_LIMITS.maxVerbsPerFamily) {
      errors.push({
        field: familyRef,
        message: `Family "${family}" has too many verbs (${verbs.length} > ${PACK_LIMITS.maxVerbsPerFamily}).`,
      });
    }
    // Not a libraries.py rule — the server happily stores a family with no verbs. This
    // is a client-only UX safeguard: a named-but-empty family is very easy to create by
    // accident with chip inputs ("name it, then go add verbs") and was silently dropped
    // by an earlier version of the draft-to-record conversion. Surface it instead.
    if (verbs.length === 0) {
      errors.push({ field: familyRef, message: `Family "${family}" needs at least one verb.` });
    }
    for (const rawVerb of verbs) {
      const verb = normalizeVerb(rawVerb);
      const verbRef: PackFieldRef = { kind: "verb", family, verb: rawVerb };
      const alphaError = verbTokenError(verb);
      if (alphaError) {
        errors.push({
          field: verbRef,
          message: `Verb "${rawVerb}" in family "${family}" must be alphabetic.`,
        });
        continue;
      }
      const seenFamily = seenVerbs.get(verb);
      if (seenFamily !== undefined && seenFamily !== family) {
        errors.push({
          field: verbRef,
          message: `Verb "${verb}" appears in both "${seenFamily}" and "${family}" within this pack.`,
        });
      }
      seenVerbs.set(verb, family);
    }
  }

  return errors;
}
