import type { DegreeFormat, Education } from "./resumeEdit";

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

type DegreeParts = Pick<Education, "degree_type" | "majors" | "minors" | "degree_format">;

/** The line a "generated" entry prints, from its current parts. */
export function generatedDegree(edu: DegreeParts): string {
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
  };
}
