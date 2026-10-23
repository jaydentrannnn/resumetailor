import { request } from "./core";

/** What one mailbox check did (`mail_inbox.IngestResult`). */
export type MailCheckResult = {
  matched: number;
  unclear: number;
  ignored: number;
  already_seen: number;
  /** Confident rejections closed automatically. */
  closed: number;
};

/** The mailbox the app checks itself (`routes/mail_account.AccountView`); never the password. */
export type MailAccount = {
  host: string;
  port: number;
  username: string;
  password_set: boolean;
  /** Hours between automatic checks; 0 checks only on request. */
  every_hours: number;
  auto_close: boolean;
  last_checked: string;
  last_error: string;
  last_result: MailCheckResult | null;
  running: boolean;
  /** Pending rejections automatic closing would record now. */
  confident_pending: number;
};

export type MailAccountWrite = {
  host: string;
  port: number;
  username: string;
  /** Empty keeps the saved password. */
  password: string;
  every_hours: number;
  auto_close: boolean;
};

/** Hours the Settings page offers between checks (`mail_sync.CHECK_EVERY`). */
export const MAIL_CHECK_EVERY = [0, 1, 3, 6, 12] as const;

export function getMailAccount(): Promise<MailAccount> {
  return request("/api/mail/account");
}

export function saveMailAccount(body: MailAccountWrite): Promise<MailAccount> {
  return request("/api/mail/account", { method: "PUT", body: JSON.stringify(body) });
}

/** Forget the account and its password; email updates already read stay. */
export function removeMailAccount(): Promise<MailAccount> {
  return request("/api/mail/account", { method: "DELETE" });
}

/** Log in once with these values (blank ones fall back to the saved account). */
export function testMailAccount(
  body: Pick<MailAccountWrite, "host" | "port" | "username" | "password">,
): Promise<{ folders: number }> {
  return request("/api/mail/account/test", { method: "POST", body: JSON.stringify(body) });
}

/** Start a check now; its result shows on the next read of the account or the Tracker. */
export function checkMailNow(): Promise<MailAccount> {
  return request("/api/mail/account/check", { method: "POST" });
}
