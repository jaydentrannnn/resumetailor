import type { JobBullet, RerenderRequest } from "../api";

export type BulletMode = "ai" | "edit" | "original" | "remove";

export interface BulletChoice {
  mode: BulletMode;
  /** The typed text while `mode === "edit"`. */
  text: string;
}

export type ReviewState = Record<string, BulletChoice>;

/** The saved state of each bullet, read back from what the last render used. */
export function choiceFromRow(row: JobBullet): BulletChoice {
  if (row.current_text == null) return { mode: "remove", text: row.ai_text };
  if (row.current_text === row.ai_text) return { mode: "ai", text: row.ai_text };
  if (row.merged_from.length === 0 && row.current_text === row.source_text)
    return { mode: "original", text: row.ai_text };
  return { mode: "edit", text: row.current_text };
}

export function initialReview(rows: JobBullet[]): ReviewState {
  return Object.fromEntries(rows.map((r) => [r.bullet_id, choiceFromRow(r)]));
}

/** Everything back to the AI's version. */
export function resetToAi(rows: JobBullet[]): ReviewState {
  return Object.fromEntries(rows.map((r) => [r.bullet_id, { mode: "ai", text: r.ai_text }]));
}

function same(a: BulletChoice, b: BulletChoice): boolean {
  if (a.mode !== b.mode) return false;
  return a.mode !== "edit" || a.text.trim() === b.text.trim();
}

/** Bullets whose choice differs from what is rendered now. */
export function pendingCount(rows: JobBullet[], state: ReviewState): number {
  return rows.filter((r) => state[r.bullet_id] && !same(state[r.bullet_id], choiceFromRow(r)))
    .length;
}

/** The request body: the full set of changes relative to the AI version. An edit
 * that matches the AI text is no edit at all. */
export function toRequest(
  state: ReviewState,
  rows: JobBullet[],
  confirmed: string[] = [],
): RerenderRequest {
  const body: RerenderRequest = { edits: {}, reverted: [], removed: [], confirmed };
  for (const row of rows) {
    const choice = state[row.bullet_id];
    if (!choice) continue;
    if (choice.mode === "remove") body.removed.push(row.bullet_id);
    else if (choice.mode === "original") body.reverted.push(row.bullet_id);
    else if (choice.mode === "edit" && choice.text.trim() !== row.ai_text.trim())
      body.edits[row.bullet_id] = choice.text.trim();
  }
  return body;
}

/** Rows grouped by "Section · Entry" in document order, for display. */
export function groupRows(
  rows: JobBullet[],
): { key: string; section: string; entry: string; rows: JobBullet[] }[] {
  const groups: { key: string; section: string; entry: string; rows: JobBullet[] }[] = [];
  for (const row of rows) {
    const key = `${row.section_title}\u0000${row.entry_label}`;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.rows.push(row);
    else groups.push({ key, section: row.section_title, entry: row.entry_label, rows: [row] });
  }
  return groups;
}
