import type { FollowUpsDue } from "../api";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The Apply page's follow-up line; empty when nothing is due or silent. A silent row
 * that is also due a follow-up is counted once, as silent. */
export function followUpSummary(due: FollowUpsDue): string {
  const nudges = due.due.filter((row) => row.due === "follow_up" && !row.stale).length;
  const thanks = due.due.filter((row) => row.due === "thank_you").length;
  const silent = due.stale.length;
  const parts = [
    nudges > 0 && `${plural(nudges, "application is", "applications are")} due a follow-up`,
    thanks > 0 && `${plural(thanks, "thank-you note", "thank-you notes")} to send`,
    silent > 0 &&
      `${plural(silent, "application has", "applications have")} had no reply in 60+ days`,
  ].filter(Boolean);
  return parts.length ? `${parts.join("; ")}.` : "";
}
