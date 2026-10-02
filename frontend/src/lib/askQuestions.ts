import type { ApplyFieldOutcome, ApplyReviewField } from "../api";

const WRITTEN = new Set(["textarea", "text"]);
const OPEN = new Set(["unanswered", "manual_review"]);
const MAX = 8;

/**
 * Written-answer questions the last fill left open, for the Ask the AI card to offer.
 * A field the review snapshot knows is kept only when it is a text box; one it does not
 * know is kept when its label reads like a question.
 */
export function unansweredQuestions(
  fill:
    | {
        field_outcomes?: ApplyFieldOutcome[];
        review_fields?: ApplyReviewField[];
      }
    | null
    | undefined,
): string[] {
  const kinds = new Map((fill?.review_fields ?? []).map((f) => [f.field_id, f.control_kind]));
  const out: string[] = [];
  for (const outcome of fill?.field_outcomes ?? []) {
    const label = outcome.label?.trim();
    if (!label || !outcome.state || !OPEN.has(outcome.state) || out.includes(label)) continue;
    const kind = outcome.field_id ? kinds.get(outcome.field_id) : undefined;
    if (kind ? !WRITTEN.has(kind) : !(label.includes("?") || label.length > 40)) continue;
    out.push(label);
    if (out.length === MAX) break;
  }
  return out;
}
