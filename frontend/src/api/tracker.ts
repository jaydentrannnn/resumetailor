import { request } from "./core";
import type { MailProposal } from "./mailUpdates";

/** A board column (`apply/funnel/tracker.Column`); `hired` cards sit under offer. */
export type TrackerColumn = "not_sent" | "applied" | "assessment" | "interview" | "offer" | "closed";

/** Why a card closed; a move to Closed names one. */
export type TrackerReason = "rejected" | "ghosted" | "withdrawn" | "offer_declined";

/** One Done application on the board. */
export type TrackerCard = {
  id: string;
  company: string;
  role: string;
  location: string;
  source: string;
  column: TrackerColumn;
  /** The hiring label ("Interviewing", "Rejected"), or why it was never sent. */
  label: string;
  /** For a closed card, the furthest stage it reached ("Interviewing"). */
  reached: string;
  closed: string | null;
  stage: string | null;
  stage_dates: Record<string, string>;
  sent_on: string | null;
  last_update: string;
  /** Pending email updates about this application. */
  proposals: MailProposal[];
};

export type TrackerBoard = {
  cards: TrackerCard[];
  /** Email updates with no card on the board (unmatched, or about a row not in Done). */
  unmatched: MailProposal[];
  counts: Record<TrackerColumn, number>;
  last_synced: string;
};

/** What a move changed, so Undo reverses exactly that. */
export type TrackerReceipt = { added: string[]; voided: string[] };

const cardPath = (id: string, action: string) =>
  `/api/tracker/${encodeURIComponent(id)}/${action}`;

/** Every Done application as a card, with its pending email updates. */
export function getTrackerBoard(): Promise<TrackerBoard> {
  return request("/api/tracker");
}

/** Move a card by recording (or voiding) outcome events. */
export function moveTrackerCard(
  id: string,
  column: TrackerColumn,
  reason?: TrackerReason,
): Promise<{ card: Omit<TrackerCard, "proposals">; receipt: TrackerReceipt }> {
  return request(cardPath(id, "move"), {
    method: "POST",
    body: JSON.stringify({ column, reason: reason ?? null }),
  });
}

/** Reverse one move, as long as the card has not changed since. */
export function undoTrackerMove(
  id: string,
  receipt: TrackerReceipt,
): Promise<Omit<TrackerCard, "proposals">> {
  return request(cardPath(id, "undo"), { method: "POST", body: JSON.stringify({ receipt }) });
}
