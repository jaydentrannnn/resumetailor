import { useCallback, useEffect, useState } from "react";
import { checkMailNow, getMailAccount, MAIL_CHECK_EVERY, saveMailAccount, type MailAccount } from "../../api";
import { Button, Card, Skeleton, SettingRow, Switch } from "../../components/ui";
import { describe } from "../../lib/errors";
import { relativeTime } from "../../lib/sources";
import { useToast } from "../../lib/toast";
import { EmailAccountForm } from "./EmailAccountForm";

const POLL_MS = 2000;

function lastCheck(account: MailAccount): string {
  if (account.running) return "Checking now…";
  if (!account.last_checked) return "Not checked yet.";
  const r = account.last_result;
  const found = r ? ` ${r.matched + r.unclear} job ${r.matched + r.unclear === 1 ? "email" : "emails"} new${r.closed ? `, ${r.closed} closed` : ""}.` : "";
  return `Checked ${relativeTime(account.last_checked)}.${found}`;
}

/**
 * Settings › Email: the mailbox the app reads job email from (IMAP, read-only), how
 * often, and whether confident rejections close on their own.
 */
export function EmailSection() {
  const toast = useToast();
  const [account, setAccount] = useState<MailAccount | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);

  const load = useCallback(() => {
    getMailAccount().then(setAccount, setLoadError);
  }, []);
  useEffect(() => {
    load();
    // The scheduled check may start or finish while the page is open elsewhere.
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, [load]);
  // A check runs on the server; ask again until it finishes.
  useEffect(() => {
    if (!account?.running) return;
    const timer = window.setTimeout(load, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [account, load]);

  if (!account) {
    return loadError ? <p className="text-sm text-danger">{describe(loadError).detail}</p> : <Skeleton className="h-64 w-full" />;
  }
  const configured = Boolean(account.host);

  async function patch(change: Partial<Pick<MailAccount, "every_hours" | "auto_close">>) {
    if (!account) return;
    const next = { ...account, ...change };
    setAccount(next);
    try {
      setAccount(await saveMailAccount({ host: next.host, port: next.port, username: next.username, password: "", every_hours: next.every_hours, auto_close: next.auto_close }));
    } catch (err) {
      setAccount(account);
      toast.error("Could not save that setting", describe(err).detail);
    }
  }

  async function checkNow() {
    try {
      setAccount(await checkMailNow());
    } catch (err) {
      // A scheduled check that started first is not an error: show it running.
      const fresh = await getMailAccount().catch(() => null);
      if (fresh) setAccount(fresh);
      if (!fresh?.running) toast.error("Could not check email", describe(err).detail);
    }
  }

  return (
    <div className="space-y-10">
      <Card
        title="Email account"
        description="The app reads job email from your mailbox over IMAP and turns it into updates on the Tracker. Read-only: the app never marks, moves or deletes mail."
      >
        <EmailAccountForm
          key={account.host + account.username}
          account={account}
          onSaved={(next) => {
            setAccount(next);
            // Saving can start the first scheduled check.
            window.setTimeout(load, POLL_MS);
          }}
        />
      </Card>
      <Card title="Checking" description="Only email from hiring systems or companies you applied to is read past its subject line.">
        <SettingRow label="Check every" layout="action">
          <select
            aria-label="Check every"
            className="field w-auto"
            disabled={!configured}
            value={account.every_hours}
            onChange={(e) => void patch({ every_hours: Number(e.target.value) })}
          >
            {MAIL_CHECK_EVERY.map((hours) => (
              <option key={hours} value={hours}>
                {hours === 0 ? "Only when I ask" : hours === 1 ? "1 hour" : `${hours} hours`}
              </option>
            ))}
          </select>
        </SettingRow>
        <SettingRow
          label="Close confident rejections automatically"
          description={
            <>
              A rejection that names the role of one application you sent closes it on the Tracker, with Undo.
              Everything else waits for you to accept.
              {account.confident_pending > 0 && ` ${account.confident_pending} would close now.`}
            </>
          }
          layout="action"
        >
          <Switch
            label="Close confident rejections automatically"
            checked={account.auto_close}
            disabled={!configured}
            onChange={(on) => void patch({ auto_close: on })}
          />
        </SettingRow>
        <SettingRow label="Last check" description={account.last_error ? undefined : lastCheck(account)} layout="action">
          {account.last_error && (
            <p role="alert" className="text-xs text-danger">
              {account.last_error}
            </p>
          )}
          <Button onClick={() => void checkNow()} disabled={!configured || account.running} loading={account.running}>
            Check now
          </Button>
        </SettingRow>
      </Card>
    </div>
  );
}
