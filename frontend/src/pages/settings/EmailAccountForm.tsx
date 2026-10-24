import { useState } from "react";
import {
  removeMailAccount,
  saveMailAccount,
  testMailAccount,
  type CheckResult,
  type MailAccount,
} from "../../api";
import { Button, SettingRow, StatusChip, StatusMark } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { CheckResultLine } from "./CheckResultLine";

/** Server, username and a write-only password for the mailbox the app reads. */
export function EmailAccountForm({
  account,
  onSaved,
}: {
  account: MailAccount;
  onSaved: (next: MailAccount) => void;
}) {
  const toast = useToast();
  const [host, setHost] = useState(account.host);
  const [port, setPort] = useState(String(account.port || 993));
  const [username, setUsername] = useState(account.username);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"" | "test" | "save" | "remove">("");
  const [result, setResult] = useState<CheckResult | null>(null);
  const [failure, setFailure] = useState("");
  const configured = Boolean(account.host);
  const fields = {
    host: host.trim(),
    port: Number(port) || 993,
    username: username.trim(),
    password,
  };
  const ready = Boolean(fields.host && fields.username && (password || account.password_set));

  async function run(kind: "test" | "save" | "remove", work: () => Promise<void>) {
    setBusy(kind);
    try {
      await work();
    } finally {
      setBusy("");
    }
  }

  const test = () =>
    run("test", async () => {
      setResult(null);
      setFailure("");
      try {
        const { folders } = await testMailAccount(fields);
        setResult({
          ok: true,
          detail: `Signed in; ${folders} ${folders === 1 ? "folder" : "folders"} to read.`,
        });
      } catch (err) {
        setFailure(describe(err).detail);
      }
    });

  const save = () =>
    run("save", async () => {
      try {
        const next = await saveMailAccount({
          ...fields,
          every_hours: account.every_hours,
          auto_close: account.auto_close,
        });
        setPassword("");
        onSaved(next);
        toast.success("Email account saved");
      } catch (err) {
        toast.error("Could not save the email account", describe(err).detail);
      }
    });

  const remove = () =>
    run("remove", async () => {
      try {
        const next = await removeMailAccount();
        setHost("");
        setUsername("");
        setPassword("");
        setResult(null);
        setFailure("");
        onSaved(next);
        toast.success("Email account removed");
      } catch (err) {
        toast.error("Could not remove the email account", describe(err).detail);
      }
    });

  return (
    <div>
      <SettingRow
        label="Server"
        description="Your mail provider's IMAP server, for example mail.example.com."
      >
        <input
          aria-label="IMAP server"
          className="field min-w-0 flex-1"
          spellCheck={false}
          autoComplete="off"
          value={host}
          onChange={(e) => setHost(e.target.value)}
        />
        <input
          aria-label="Port"
          className="field w-20"
          inputMode="numeric"
          value={port}
          onChange={(e) => setPort(e.target.value.replace(/\D/g, "").slice(0, 5))}
        />
      </SettingRow>
      <SettingRow label="Username" description="Usually your full email address.">
        <input
          aria-label="Username"
          className="field min-w-0 flex-1"
          spellCheck={false}
          autoComplete="off"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </SettingRow>
      <SettingRow
        label={
          <span className="flex items-center gap-2">
            Password
            <StatusChip tone={account.password_set ? "done" : "muted"}>
              {account.password_set ? "Saved" : "Not set"}
            </StatusChip>
          </span>
        }
        description="Kept in your system's credential store; never shown again."
      >
        <input
          aria-label="Password"
          type="password"
          autoComplete="off"
          className="field min-w-0 flex-1"
          placeholder={
            account.password_set ? "Type a new password to replace it" : "Your email password"
          }
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </SettingRow>
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <Button
          variant="primary"
          onClick={save}
          loading={busy === "save"}
          disabled={!ready || !!busy}
        >
          Save
        </Button>
        <Button onClick={test} loading={busy === "test"} disabled={!ready || !!busy}>
          Test connection
        </Button>
        {configured && (
          <Button
            variant="danger"
            className="ml-auto"
            onClick={remove}
            loading={busy === "remove"}
            disabled={!!busy}
          >
            Remove account
          </Button>
        )}
      </div>
      {result && <CheckResultLine result={result} />}
      {failure && (
        <div role="alert" className="mt-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-danger">
            <StatusMark tone="failed" />
            Could not connect
          </p>
          <p className="mt-1 text-ink">{failure}</p>
        </div>
      )}
    </div>
  );
}
