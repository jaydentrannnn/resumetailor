/** The review step of a resume merge: which incoming entry is the same as which. */
import type { MergePair } from "../api";
import { countLabel } from "./countLabel";

/** What the student picked per pair key: an existing entry's ref, or "new". */
export type MergePicks = Record<string, string>;

/** The proposal as picks, the starting point of the review list. */
export function proposedPicks(pairs: MergePair[]): MergePicks {
  return Object.fromEntries(pairs.map((pair) => [pair.key, pair.match ?? "new"]));
}

/**
 * Only the picks that differ from the proposal: what the server needs to hear. An
 * unchanged pair is left to the same rule that proposed it, so a review that changes
 * nothing merges exactly as the preview said.
 */
export function changedPicks(pairs: MergePair[], picks: MergePicks): MergePicks {
  return Object.fromEntries(
    pairs
      .filter((pair) => (picks[pair.key] ?? pair.match ?? "new") !== (pair.match ?? "new"))
      .map((pair) => [pair.key, picks[pair.key]]),
  );
}

/** Whether two incoming entries were pointed at the same existing entry. */
export function duplicateTargets(picks: MergePicks): boolean {
  const refs = Object.values(picks).filter((ref) => ref !== "new");
  return new Set(refs).size !== refs.length;
}

/** "2 will be updated, 1 will be added" for the pairs as currently picked. */
export function reviewSummary(pairs: MergePair[], picks: MergePicks): string {
  const added = pairs.filter((pair) => (picks[pair.key] ?? pair.match ?? "new") === "new").length;
  const updated = pairs.length - added;
  return [
    updated ? `${countLabel(updated, "entry", "entries")} will be updated` : "",
    added ? `${countLabel(added, "entry", "entries")} will be added` : "",
  ]
    .filter(Boolean)
    .join(", ");
}

/** The note under a pair: why it was proposed and what it brings. */
export function pairNote(pair: MergePair, pick: string): string {
  const bullets = countLabel(pair.new_bullets, "new bullet");
  if (pick === "new" && pair.suggested)
    return `Added as a new entry. It has the same dates and a similar title as ${pair.suggested_name}; if it is the same job, pick that above.`;
  if (pick === "new") return "Added as a new entry.";
  if (pick !== pair.match)
    return "Its bullets are added to the entry you picked; nothing is removed.";
  return `Proposed because of the ${pair.reason}. ${bullets}; nothing is removed.`;
}
