import { KeyRow } from "./KeyRow";
import { useCallback, useEffect, useId, useState } from "react";
import {
  fetchLocalModels,
  fetchSecrets,
  testModel,
  type CheckResult,
  type SecretState,
} from "../../api";
import { Button, Card, InlineHelp } from "../../components/ui";
import { emitAppEvent } from "../../lib/appEvents";
import { describe } from "../../lib/errors";
import { GLOSSARY } from "../../lib/glossary";
import { profileDefaultModel } from "../../lib/modelLabel";
import { PROVIDERS, providerInfo } from "../../lib/providers";
import { useToast } from "../../lib/toast";
import { useRunState } from "../../state/runState";
import { CheckResultLine } from "./CheckResultLine";
import { SettingRow } from "./SettingRow";

/**
 * Settings → Models: which AI to use, its keys, and a live connection test. `embedded`
 * (the onboarding Model step) drops the two tiles for hairline-separated sections.
 */
export function ModelsSection({ embedded = false }: { embedded?: boolean } = {}) {
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
    <div className="space-y-4">
      <Card
        embedded={embedded}
        title="AI model"
        description="Used for every tailoring run and for answering application questions."
      >
        <SettingRow
          label="Provider"
          layout="stacked"
          description="Choose where the model runs. Local providers need no API key."
        >
          <ProviderPicker
            options={options}
            value={settings.model}
            disabled={!settingsLoaded}
            onPick={(id) => setSettings({ ...settings, model: id, model_name: null })}
          />
        </SettingRow>

        <div className="mt-4 grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="rt-model-label font-medium text-ink">Model</span>
            <input
              className="field mt-1 font-mono"
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
            <span className="rt-model-label gap-1 font-medium text-ink">
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

        <div className="mt-4 border-t border-line pt-4">
          <SettingRow
            label="Connection"
            layout="action"
            description={
              <>
                {result ? (
                  <CheckResultLine result={result} />
                ) : (
                  "Send a small request to check the selected model."
                )}
                {!provider?.local && (
                  <p className="mt-2">
                    {settings.model === "ollama-cloud"
                      ? "The test sends one tiny request (counts toward your Ollama plan)."
                      : "The test sends one tiny request (a fraction of a cent)."}
                  </p>
                )}
              </>
            }
          >
            <div className="flex w-full flex-wrap items-center justify-end gap-3">
              {provider?.link && (
                <a
                  className="rt-link text-sm font-medium"
                  href={provider.link.href}
                  target="_blank"
                  rel="noreferrer"
                >
                  {provider.link.label}
                </a>
              )}
              <Button variant="secondary" loading={testing} onClick={runTest}>
                Test connection
              </Button>
            </div>
          </SettingRow>
        </div>
        {needsKey && (
          <p className="mt-3 rounded-sm bg-attn-soft px-3 py-2 text-sm text-attn">
            {provider?.name} needs an API key. Add it below.
          </p>
        )}
      </Card>

      <Card
        embedded={embedded}
        className={embedded ? "border-t border-line pt-4" : ""}
        title="API keys"
        description={
          storeBackend === "keyring"
            ? "Saved in your system keychain, never in plain files. Keys set in a .env file take priority."
            : "Saved encrypted in your data folder. Keys set in a .env file take priority."
        }
      >
        <ul className="divide-y divide-line">
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

/** The provider radio list: name and one-line summary, the chosen one marked. */
function ProviderPicker({
  options,
  value,
  disabled,
  onPick,
}: {
  options: string[];
  value: string;
  disabled: boolean;
  onPick: (id: string) => void;
}) {
  return (
    <fieldset disabled={disabled} className="divide-y divide-line">
      <legend className="sr-only">Provider</legend>
      {options.map((id) => {
        const info = providerInfo(id);
        const checked = value === id;
        return (
          <label
            key={id}
            className={`flex cursor-pointer gap-3 py-3 first:pt-0 ${
              checked ? "text-accent" : "text-ink-muted"
            }`}
          >
            <input
              type="radio"
              name="provider"
              className="mt-1"
              checked={checked}
              onChange={() => onPick(id)}
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
  );
}
