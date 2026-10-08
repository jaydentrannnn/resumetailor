import { useId, useState } from "react";
import { deleteSecret, saveSecret, type SecretState } from "../../api";
import { Button, StatusChip } from "../../components/ui";
import { emitAppEvent } from "../../lib/appEvents";
import { describe } from "../../lib/errors";
import { KEY_HELP, KEY_LABELS } from "../../lib/providers";
import { useToast } from "../../lib/toast";
export function KeyRow({
  secret,
  highlighted,
  onChange,
}: {
  secret: SecretState;
  highlighted: boolean;
  onChange: () => void;
}) {
  const toast = useToast();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const inputId = useId();
  const status = secret.set ? (secret.source === "env" ? "Set in .env" : "Saved") : "Not set";

  async function save() {
    setBusy(true);
    try {
      await saveSecret(secret.name, value.trim());
      setValue("");
      toast.success("Key saved");
      emitAppEvent("rt:setup-changed");
      onChange();
    } catch (err) {
      const d = describe(err);
      toast.error("Could not save the key", d.detail);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await deleteSecret(secret.name);
      toast.success("Key removed");
      emitAppEvent("rt:setup-changed");
      onChange();
    } catch (err) {
      toast.error("Could not remove the key", describe(err).detail);
    } finally {
      setBusy(false);
    }
  }

  const help = KEY_HELP[secret.name];

  return (
    <li className="min-w-0 space-y-2 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <label
          htmlFor={inputId}
          className={`text-sm font-medium ${highlighted ? "text-accent" : "text-ink"}`}
        >
          {KEY_LABELS[secret.name] ?? secret.name}
        </label>
        {help && (
          <a href={help.href} target="_blank" rel="noopener noreferrer" className="rt-link text-xs">
            {help.label}
          </a>
        )}
        <StatusChip tone={secret.set ? "done" : "muted"}>{status}</StatusChip>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-2 sm:flex-nowrap">
        <input
          id={inputId}
          type="password"
          autoComplete="off"
          spellCheck={false}
          className="field min-w-0 flex-1 basis-full sm:basis-0"
          placeholder={secret.set ? "Paste a new key to replace it" : "Paste your key"}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button onClick={save} loading={busy} disabled={!value.trim()}>
          Save
        </Button>
        {secret.source === "saved" && (
          <Button variant="ghost" onClick={remove} disabled={busy}>
            Remove
          </Button>
        )}
      </div>
    </li>
  );
}
