/** Openers that describe a duty instead of an achievement. */
const WEAK_OPENERS = [
  "responsible for",
  "helped",
  "helping",
  "worked on",
  "working on",
  "assisted",
  "assisting",
  "participated in",
  "involved in",
  "tasked with",
  "duties included",
  "in charge of",
];

export type BulletHint = {
  code: "no_metric" | "weak_verb" | "too_long" | "repeat_verb";
  message: string;
};

/** The bullet's opening word, lowercased ("Led," -> "led"). */
export function firstVerb(text: string): string {
  return (/^[^A-Za-z]*([A-Za-z][A-Za-z'-]*)/.exec(text)?.[1] ?? "").toLowerCase();
}

/**
 * Non-blocking coaching for one bullet, computed in the browser. `charsPerLine` is the
 * calibrated line width (0 when unknown); `siblings` are the other bullets in the entry.
 */
export function lintBullet(
  text: string,
  { charsPerLine = 0, siblings = [] }: { charsPerLine?: number; siblings?: string[] } = {},
): BulletHint[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  const hints: BulletHint[] = [];
  const lower = trimmed.toLowerCase();
  const weak = WEAK_OPENERS.find((opener) => lower === opener || lower.startsWith(`${opener} `));
  if (weak)
    hints.push({
      code: "weak_verb",
      message: `Starts with "${trimmed.slice(0, weak.length)}". Lead with what you did: Built, Led, Analyzed…`,
    });
  const verb = firstVerb(trimmed);
  if (verb && siblings.some((other) => firstVerb(other) === verb))
    hints.push({
      code: "repeat_verb",
      message: `Another bullet here also starts with "${verb}". Vary the opening verb.`,
    });
  if (!/\d/.test(trimmed))
    hints.push({
      code: "no_metric",
      message: "No number. Add a count, %, $ or time saved if you have one.",
    });
  if (charsPerLine > 0 && trimmed.length > charsPerLine * 2)
    hints.push({
      code: "too_long",
      message: `About ${Math.ceil(trimmed.length / charsPerLine)} lines on your template; 1–2 lines reads best.`,
    });
  return hints;
}
