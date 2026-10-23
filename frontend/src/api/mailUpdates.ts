import { request } from "./core";

/** What a job email says happened (`mail_signals.Signal`); "sent" confirms a send. */
export type MailSignal = "sent" | "assessment" | "interview_invited" | "offer" | "rejected";

/** An application an unclear email could be about. */
export type MailCandidate = { id: string; company: string; role: string; stage: string };

/** One job email Claude Desktop read, waiting to be accepted or dismissed. */
export type MailProposal = {
  id: string;
  message_id: string;
  received_on: string | null;
  sender: string;
  from_domain: string;
  subject: string;
  excerpt: string;
  signal: MailSignal | null;
  app_id: string | null;
  candidates: string[];
  reason: string;
  /** Why this needs a second look (it contradicts what is recorded); "" when it fits. */
  flag: string;
  state: "pending" | "accepted" | "dismissed";
  company: string;
  role: string;
  /** The application's hiring stage now. */
  stage: string;
  options: MailCandidate[];
};

const proposalPath = (id: string, action: string) =>
  `/api/mail/proposals/${encodeURIComponent(id)}/${action}`;

/** Email updates still waiting on the student, newest email first. */
export function getMailProposals(): Promise<{ proposals: MailProposal[] }> {
  return request("/api/mail/proposals");
}

/** Record one email update on its application (or the one picked here). */
export function acceptMailProposal(
  id: string,
  body: { signal?: MailSignal; app_id?: string } = {},
): Promise<MailProposal> {
  return request(proposalPath(id, "accept"), { method: "POST", body: JSON.stringify(body) });
}

/** Drop an email update; nothing is recorded. */
export function dismissMailProposal(id: string): Promise<MailProposal> {
  return request(proposalPath(id, "dismiss"), { method: "POST" });
}
