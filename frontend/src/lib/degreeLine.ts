import type { DegreeFormat, Education, MajorEntry } from "./resumeEdit";

// Mirrors `resume_tailor/content/degree_line.py` so the editor previews exactly what the
// server prints on save. Keep the two in step (`degreeLine.test.ts` pins the same cases
// as `tests/content/test_degree_line.py`).

const SEPARATORS: Record<DegreeFormat, string> = { semicolon: "; ", comma: ", ", pipe: " | " };

/** "X", "X and Y", "X, Y and Z". */
export function joinNames(names: string[]): string {
  const kept = names.map((n) => n.trim()).filter(Boolean);
  if (kept.length <= 2) return kept.join(" and ");
  return `${kept.slice(0, -1).join(", ")} and ${kept[kept.length - 1]}`;
}

/** "B.A. in Economics and Math; Minor in Art". Empty parts are left out. */
export function composeDegree(
  degreeType: string,
  majors: string[],
  minors: string[],
  format: DegreeFormat = "semicolon",
): string {
  const kind = degreeType.trim();
  const fields = joinNames(majors);
  const head = kind && fields ? `${kind} in ${fields}` : kind || fields;
  const minorNames = minors.filter((m) => m.trim());
  if (!minorNames.length) return head;
  const minor = `${minorNames.length > 1 ? "Minors" : "Minor"} in ${joinNames(minorNames)}`;
  return head ? `${head}${SEPARATORS[format] ?? "; "}${minor}` : minor;
}

const MINOR_RE = /\s*(?:[;,|]|\band\b)?\s*\bminors?\s+in\s+(.+)$/i;
const IN_RE = /^(.+?)\s+in\s+(.+)$/;
const ABBREV_RE = /^((?:[A-Z]\.?){1,4}[A-Za-z]?\.?)\s+(.+)$/;

function split(text: string): string[] {
  return text
    .replace(/^[\s;,|.]+|[\s;,|.]+$/g, "")
    .split(/\s*(?:,|&|\band\b)\s*/)
    .filter(Boolean);
}

/** Best guess at `[degreeType, majors, minors]` in a typed degree line. */
export function detectDegree(degree: string): [string, string[], string[]] {
  let text = degree.trim().replace(/\s*\|\s*GPA:.*$/i, "");
  let minors: string[] = [];
  const minor = MINOR_RE.exec(text);
  if (minor) {
    minors = split(minor[1]);
    text = text.slice(0, minor.index).replace(/^[\s;,|]+|[\s;,|]+$/g, "");
  }
  const found = IN_RE.exec(text) ?? ABBREV_RE.exec(text);
  if (found) return [found[1].trim(), split(found[2]), minors];
  return ["", split(text), minors];
}

type DegreeParts = Pick<
  Education,
  "degree_type" | "majors" | "major_entries" | "minors" | "degree_format"
>;

export function majorEntries(edu: DegreeParts): MajorEntry[] {
  return (
    edu.major_entries ??
    (edu.majors ?? []).map((name) => ({ name, degree_type: edu.degree_type ?? "" }))
  );
}

function degreeKey(value: string): string {
  const key = value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const aliases: Record<string, string> = {
    bachelorofscience: "bs",
    bachelorscience: "bs",
    bachelorsdegreeinscience: "bs",
    bsc: "bs",
    bachelorofarts: "ba",
    bachelorarts: "ba",
    bachelorsdegreeinarts: "ba",
    masterofscience: "ms",
    msc: "ms",
    masterofarts: "ma",
    associateofscience: "as",
    associateofarts: "aa",
    doctorofphilosophy: "phd",
  };
  return aliases[key] ?? key;
}

/** The line a "generated" entry prints, from its current parts. */
export function generatedDegree(edu: DegreeParts): string {
  if (edu.major_entries !== undefined) {
    const groups = new Map<string, { type: string; names: string[] }>();
    for (const entry of edu.major_entries) {
      const type = entry.degree_type.trim();
      const key = degreeKey(type);
      if (!groups.has(key)) groups.set(key, { type, names: [] });
      if (entry.name.trim()) groups.get(key)!.names.push(entry.name.trim());
    }
    const clauses = [...groups.values()].map((group) => composeDegree(group.type, group.names, []));
    if (edu.minors?.length) clauses.push(composeDegree("", [], edu.minors));
    return clauses.filter(Boolean).join(SEPARATORS[edu.degree_format ?? "semicolon"]);
  }
  return composeDegree(
    edu.degree_type ?? "",
    edu.majors ?? [],
    edu.minors ?? [],
    edu.degree_format ?? "semicolon",
  );
}

/** `edu` with `patch` applied; a "generated" entry's printed line follows its parts. */
export function withDegreeParts<T extends Education>(edu: T, patch: Partial<T>): T {
  const next = { ...edu, ...patch };
  if (patch.major_entries !== undefined) {
    next.majors = patch.major_entries.map((entry) => entry.name);
    next.degree_type = patch.major_entries[0]?.degree_type ?? "";
  } else if (patch.majors !== undefined || patch.degree_type !== undefined) {
    next.major_entries = (next.majors ?? []).map((name) => ({
      name,
      degree_type: next.degree_type ?? "",
    }));
  }
  return next.degree_mode === "generated" ? { ...next, degree: generatedDegree(next) } : next;
}

/** `edu` with its type/majors/minors read from the typed line (only fills blanks). */
export function withDetectedParts<T extends Education>(edu: T): T {
  const [degreeType, majors, minors] = detectDegree(edu.degree);
  return {
    ...edu,
    degree_type: edu.degree_type || degreeType,
    majors: edu.majors?.length ? edu.majors : majors,
    minors: edu.minors?.length ? edu.minors : minors,
    major_entries: majorEntries(edu).length
      ? majorEntries(edu).map((entry) => ({
          ...entry,
          degree_type: entry.degree_type || degreeType,
        }))
      : majors.map((name) => ({ name, degree_type: edu.degree_type || degreeType })),
  };
}
