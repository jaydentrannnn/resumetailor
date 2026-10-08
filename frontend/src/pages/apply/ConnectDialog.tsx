import { useState } from "react";
import { saveSecret } from "../../api";
import { Button, Modal } from "../../components/ui";
import { describe } from "../../lib/errors";
import { PROVIDER_KEYS, PROVIDER_LABELS, type SearchProvider } from "../../lib/sources";
const KEY_LINKS: Record<SearchProvider, string> = {
  adzuna: "https://developer.adzuna.com/signup",
  usajobs: "https://developer.usajobs.gov/apirequest/",
};

/**
 * Save a search engine's API keys once (OS keychain, through `/api/secrets`; values are
 * never read back). Every search on that engine then works.
 */
export function ConnectDialog({
  provider,
  savedKeys,
  onSaved,
  onClose,
}: {
  provider: SearchProvider;
  savedKeys: Set<string>;
  onSaved: () => void;
  onClose: () => void;
}) {
  const label = PROVIDER_LABELS[provider];
  const keys = PROVIDER_KEYS[provider];
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const complete = keys.every((k) => savedKeys.has(k.name) || values[k.name]?.trim());

  async function save() {
    setSaving(true);
    setError("");
    try {
      for (const key of keys) {
        const value = values[key.name]?.trim();
        if (value) await saveSecret(key.name, value);
      }
      onSaved();
      onClose();
    } catch (reason) {
      setError(describe(reason).detail);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Connect ${label}`} onClose={onClose}>
      <form
        className="mt-4 space-y-3 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          if (complete) void save();
        }}
      >
        <p className="text-xs text-ink-muted">
          Saved once in your system keychain and used by every {label} search.{" "}
          <a className="rt-link" href={KEY_LINKS[provider]} target="_blank" rel="noreferrer">
            Get a free key
          </a>
        </p>
        {keys.map((key) => (
          <label key={key.name} className="block text-xs">
            <span className="font-medium">{key.label}</span>
            <input
              className="field mt-1 w-full text-sm"
              type={key.name.endsWith("EMAIL") ? "email" : "password"}
              autoComplete="off"
              placeholder={savedKeys.has(key.name) ? "Saved (leave blank to keep)" : ""}
              value={values[key.name] ?? ""}
              onChange={(e) => setValues((prev) => ({ ...prev, [key.name]: e.target.value }))}
            />
          </label>
        ))}
        {error && (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end">
          <Button type="submit" variant="primary" size="sm" loading={saving} disabled={!complete}>
            Save keys
          </Button>
        </div>
      </form>
    </Modal>
  );
}
