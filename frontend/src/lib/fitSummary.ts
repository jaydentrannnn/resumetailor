import type { ApplicationRow, CoverageFunnel } from "../api";

/** Page statuses the tailored page counts as showing a must-have (`coverage.ON_PAGE`). */
const ON_PAGE = new Set(["expressed", "demonstrated"]);

/** Must-haves the tailored page shows, in posting order. */
export function pageStrengths(funnel?: CoverageFunnel | null): string[] {
  return (funnel?.keywords ?? []).filter((k) => k.page && ON_PAGE.has(k.page)).map((k) => k.phrase);
}

const NOTES: [RegExp, (...groups: string[]) => string][] = [
  [
    /^language_level:(.+)$/,
    (name) => `The posting asks for fluent ${name}; your profile lists ${name} as not fluent.`,
  ],
  [
    /^language_unlisted:(.+)$/,
    (name) => `The posting requires ${name}. Add your languages in Profile so this can be checked.`,
  ],
  [/^years_(\d+)$/, (years) => `The posting asks for ${years}+ years of experience.`],
  [
    /^seniority_mismatch$/,
    () => "The title reads early career, but the posting reads more senior.",
  ],
  [/^return_intern_wording$/, () => "The posting may be open only to returning interns."],
  [
    /^title_level_token$/,
    () => "The title carries a level (II, L4 and similar); check that it is entry level.",
  ],
  [/^enrollment wording/, () => "The posting asks that you be enrolled in school."],
];

/**
 * What screening flagged without rejecting, in plain words: languages, years asked for,
 * seniority and enrollment wording. Codes with no note (such as an unknown posting date)
 * are left out.
 */
export function fitChecks(app: Pick<ApplicationRow, "screen" | "eligibility_flags">): string[] {
  const codes = new Set([...(app.eligibility_flags ?? []), ...(app.screen?.flags ?? [])]);
  const notes: string[] = [];
  for (const code of codes) {
    for (const [pattern, note] of NOTES) {
      const match = pattern.exec(code);
      if (match) {
        notes.push(note(...match.slice(1)));
        break;
      }
    }
  }
  return [...new Set(notes)];
}
