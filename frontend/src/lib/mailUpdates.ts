import type { MailProposal, MailSignal } from "../api";

/** What each email signal is called in the Email updates list. */
export const SIGNAL_LABELS: Record<MailSignal, string> = {
  sent: "Application received",
  assessment: "Assessment or test",
  interview_invited: "Invited to interview",
  offer: "Offer",
  rejected: "Rejected",
};

export const SIGNALS = Object.keys(SIGNAL_LABELS) as MailSignal[];

/** Matched to one application and fitting what is recorded: safe for "Accept all". */
export const readyToAccept = (proposal: MailProposal) =>
  Boolean(proposal.app_id && proposal.signal && !proposal.flag);

/** The Apply-page line, e.g. "3 job emails to review, 1 not matched". */
export function mailSummary(proposals: MailProposal[]): string {
  if (proposals.length === 0) return "";
  const unmatched = proposals.filter((p) => !p.app_id).length;
  const noun = proposals.length === 1 ? "job email" : "job emails";
  const tail = unmatched ? `, ${unmatched} not matched to an application` : "";
  return `${proposals.length} ${noun} to review${tail}. Nothing is recorded until you accept.`;
}
