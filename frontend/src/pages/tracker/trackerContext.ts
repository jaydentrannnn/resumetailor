import { createContext, useContext } from "react";
import type { MailProposal, TrackerCard } from "../../api";
import type { TrackerActions } from "../../lib/useTrackerBoard";

/** What is being dragged right now: a card onto a column, or a tray email onto a card. */
export type TrackerDrag =
  { kind: "card"; card: TrackerCard } | { kind: "email"; proposal: MailProposal };

/** An email dropped on a card, waiting for the student to confirm it. */
export type PendingEmail = { cardId: string; proposal: MailProposal };

export type TrackerContextValue = TrackerActions & {
  drag: TrackerDrag | null;
  setDrag: (drag: TrackerDrag | null) => void;
  pendingEmail: PendingEmail | null;
  setPendingEmail: (pending: PendingEmail | null) => void;
  /** Opens the application's own page (its Outcome tab once it was sent). */
  open: (card: TrackerCard) => void;
};

export const TrackerContext = createContext<TrackerContextValue | null>(null);

export function useTracker(): TrackerContextValue {
  const value = useContext(TrackerContext);
  if (!value) throw new Error("useTracker outside TrackerContext");
  return value;
}
