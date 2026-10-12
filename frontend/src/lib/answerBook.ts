import type { SavedAnswer } from "../api";

export type AnswerSource = "you" | "page" | "custom" | "ai" | "learned";

export const SOURCE_LABELS: Record<AnswerSource, string> = {
  you: "You",
  page: "From page",
  custom: "Custom",
  ai: "AI",
  learned: "Learned type",
};

/** Which badge an Answer book entry gets. */
export function answerSource(item: Pick<SavedAnswer, "kind" | "source">): AnswerSource {
  if (item.kind === "type") return "learned";
  if (item.source === "page" || item.source === "custom" || item.source === "ai") {
    return item.source;
  }
  return "you";
}

/** The entries matching `filter` ("all" keeps every one). */
export function filterAnswers(items: SavedAnswer[], filter: AnswerSource | "all"): SavedAnswer[] {
  return filter === "all" ? items : items.filter((item) => answerSource(item) === filter);
}

/** The filter choices worth showing: All plus each source present, with counts. */
export function sourceCounts(items: SavedAnswer[]): [AnswerSource, number][] {
  const counts = new Map<AnswerSource, number>();
  for (const item of items) {
    const source = answerSource(item);
    counts.set(source, (counts.get(source) ?? 0) + 1);
  }
  return (Object.keys(SOURCE_LABELS) as AnswerSource[])
    .filter((source) => counts.has(source))
    .map((source) => [source, counts.get(source) ?? 0]);
}
