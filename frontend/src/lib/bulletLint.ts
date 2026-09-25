export function suggestMissingTags(
  text: string,
  tags: string[],
  vocabLower: Set<string>,
  vocabList: string[],
): string[] {
  /**
   * Flag vocabulary words that appear in the bullet text but not its tags.
   * Tags are the fabrication guard's whitelist — a miss here is a future false positive.
   */
  const have = new Set(tags.map((t) => t.toLowerCase()));
  const lower = text.toLowerCase();
  const hits: string[] = [];
  for (const tag of vocabList) {
    if (!vocabLower.has(tag.toLowerCase())) continue;
    if (have.has(tag.toLowerCase())) continue;
    // Whole-word-ish match: avoid flagging "go" inside "google".
    const re = new RegExp(`(?:^|[^a-z0-9])${escapeReg(tag.toLowerCase())}(?:[^a-z0-9]|$)`);
    if (re.test(lower)) hits.push(tag);
  }
  return hits.slice(0, 8);
}

function escapeReg(s: string): string {
  /** Escape a string for safe use inside a RegExp. */
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

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
  code: "no_metric" | "weak_verb" | "too_long" | "no_tags" | "repeat_verb";
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
  tags: string[],
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
  if (tags.length === 0)
    hints.push({
      code: "no_tags",
      message: "No tags. Tailoring matches jobs to bullets by their tags.",
    });
  return hints;
}
