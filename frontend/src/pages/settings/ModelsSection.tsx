import { useCallback, useEffect, useId, useState } from "react";
import {
  deleteSecret,
  fetchLocalModels,
  fetchSecrets,
  saveSecret,
  testModel,
  type CheckResult,
  type SecretState,
} from "../../api";
import { Button, Card, InlineHelp } from "../../components/ui";
import { emitAppEvent } from "../../lib/appEvents";
import { describe } from "../../lib/errors";
import { GLOSSARY } from "../../lib/glossary";
import { profileDefaultModel } from "../../lib/modelLabel";
import { KEY_LABELS, PROVIDERS, providerInfo } from "../../lib/providers";
import { useToast } from "../../lib/toast";
import { useRunState } from "../../state/runState";
import { CheckResultLine } from "./CheckResultLine";

/** Settings → Models: which AI to use, its keys, and a live connection test. */
export function ModelsSection() {
  const { config, settings, setSettings, settingsLoaded } = useRunState();
  const toast = useToast();
  const [secrets, setSecrets] = useState<SecretState[]>([]);
  const [storeBackend, setStoreBackend] = useState("");
  const [local, setLocal] = useState<{ reachable: boolean; models: string[] } | null>(null);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<CheckResult | null>(null);
  const modelListId = useId();

  const provider = providerInfo(settings.model);
  const loadSecrets = useCallback(() => {
    fetchSecrets()
      .then((res) => {
        setSecrets(res.secrets);
        setStoreBackend(res.backend);
      })
      .catch((err) => toast.error("Could not load API keys", describe(err).detail));
  }, [toast]);
  useEffect(loadSecrets, [loadSecrets]);

  useEffect(() => {
    setLocal(null);
    if (settings.model !== "ollama" && settings.model !== "lmstudio") return;
    fetchLocalModels(settings.model)
      .then((res) => setLocal({ reachable: res.reachable, models: res.models }))
      .catch(() => setLocal({ reachable: false, models: [] }));
  }, [settings.model]);

  const options = (config?.model_profiles ?? PROVIDERS.map((p) => p.id)).filter(
    (id) => id !== "hybrid" || id === settings.model,
  );
  const needsKey = provider?.keys.length
    ? !secrets.some((s) => provider.keys.includes(s.name) && s.set)
    : false;

  async function runTest() {
    setTesting(true);
    setResult(null);
    try {
      const result = await testModel(settings);
      setResult(result);
      if (result.ok) emitAppEvent("rt:setup-changed");
    } catch (err) {
      setResult({ ok: false, detail: describe(err).detail });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card
        title="AI model"
        description="Used for every tailoring run and for answering application questions."
      >
        <fieldset disabled={!settingsLoaded} className="grid gap-3 sm:grid-cols-2">
          <legend className="sr-only">Provider</legend>
          {options.map((id) => {
            const info = providerInfo(id);
            const checked = settings.model === id;
            return (
              <label
                key={id}
                className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${
                  checked
                    ? "border-accent bg-accent-soft/40"
                    : "border-line hover:border-line-hover"
                }`}
              >
                <input
                  type="radio"
                  name="provider"
                  className="mt-1"
                  checked={checked}
                  onChange={() => setSettings({ ...settings, model: id, model_name: null })}
                />
                <span>
                  <span className="block font-semibold text-ink">{info?.name ?? id}</span>
                  <span className="block text-sm text-ink-muted">
                    {info?.summary ?? "Advanced routing profile."}
                  </span>
                </span>
              </label>
            );
          })}
        </fieldset>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="font-medium text-ink">Model</span>
            <input
              className="field mt-1"
              list={local?.models.length ? modelListId : undefined}
              value={settings.model_name ?? ""}
              placeholder={profileDefaultModel(settings, config)}
              onChange={(e) => setSettings({ ...settings, model_name: e.target.value || null })}
            />
            {local?.models.length ? (
              <datalist id={modelListId}>
                {local.models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            ) : null}
            <span className="mt-1 block text-xs text-ink-muted">
              Leave blank for the recommended default.
              {local && !local.reachable && provider?.local && (
                <> {provider.name} is not running, so installed models can't be listed.</>
              )}
              {local?.reachable && !local.models.length && settings.model === "ollama" && (
                <>
                  {" "}
                  No models installed yet. In a terminal run{" "}
                  <code className="font-mono">
                    ollama pull {profileDefaultModel(settings, config)}
                  </code>
                </>
              )}
            </span>
          </label>
          <label className="block text-sm">
            <span className="font-medium text-ink">
              {GLOSSARY.effort.label} <InlineHelp label="effort">{GLOSSARY.effort.help}</InlineHelp>
            </span>
            <select
              className="field mt-1"
              value={settings.effort ?? ""}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  effort: (e.target.value || null) as typeof settings.effort,
                })
              }
            >
              <option value="">Recommended per step</option>
              {(config?.effort_options ?? ["low", "medium", "high"]).map((level) => (
                <option key={level} value={level}>
                  {level[0].toUpperCase() + level.slice(1)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="primary" loading={testing} onClick={runTest}>
            Test connection
          </Button>
          {provider?.link && (
            <a
              className="text-sm font-medium text-accent underline-offset-2 hover:underline"
              href={provider.link.href}
              target="_blank"
              rel="noreferrer"
            >
              {provider.link.label}
            </a>
          )}
          {!provider?.local && (
            <span className="text-xs text-ink-muted">
              {settings.model === "ollama-cloud"
                ? "The test sends one tiny request (counts toward your Ollama plan)."
                : "The test sends one tiny request (a fraction of a cent)."}
            </span>
          )}
        </div>
        {needsKey && (
          <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
            {provider?.name} needs an API key. Add it below.
          </p>
        )}
        {result && <CheckResultLine result={result} />}
      </Card>

      <Card
        title="API keys"
        description={
          storeBackend === "keyring"
            ? "Saved in your system keychain, never in plain files. Keys set in a .env file take priority."
            : "Saved encrypted in your data folder. Keys set in a .env file take priority."
        }
      >
        <ul className="space-y-4">
          {secrets.map((secret) => (
            <KeyRow
              key={secret.name}
              secret={secret}
              highlighted={!!provider?.keys.includes(secret.name)}
              onChange={loadSecrets}
            />
          ))}
        </ul>
      </Card>
    </div>
  );
}

function KeyRow({
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

  return (
    <li className={highlighted ? "rounded-lg border border-accent/40 p-3" : "px-3"}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={inputId} className="text-sm font-medium text-ink">
          {KEY_LABELS[secret.name] ?? secret.name}
        </label>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            secret.set ? "bg-success-soft text-success" : "bg-paper text-ink-muted"
          }`}
        >
          {status}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <input
          id={inputId}
          type="password"
          autoComplete="off"
          spellCheck={false}
          className="field min-w-48 flex-1"
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
