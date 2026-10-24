import type { MailSignal } from "../api";

/** What each email signal is called in the Email updates list. */
export const SIGNAL_LABELS: Record<MailSignal, string> = {
  sent: "Application received",
  assessment: "Assessment or test",
  interview_invited: "Invited to interview",
  offer: "Offer",
  rejected: "Rejected",
};

export const SIGNALS = Object.keys(SIGNAL_LABELS) as MailSignal[];
