import { useEffect, useId, useState, type ReactNode } from "react";
import { fetchLocalModels, type CheckResult, type SecretState } from "../../api";
import { Card, InlineHelp } from "../../components/ui";
import { GLOSSARY } from "../../lib/glossary";
import { profileDefaultModel } from "../../lib/modelLabel";
import { PROVIDERS, privacyFor, providerInfo } from "../../lib/providers";
import { useRunState } from "../../state/runState";
import { ModelCheckRow } from "./ModelCheckRow";
import { SettingRow } from "./SettingRow";
import { useModelCheck } from "./useModelCheck";

/** The Tailor model: provider, model, effort and an automatic connection test. */
export function TailorModelCard({
  secrets,
  embedded = false,
  className = "",
  title = "Tailoring model",
  description = "Writes your tailored resume and cover letter.",
  onResult,
}: {
  secrets: SecretState[];
  embedded?: boolean;
  className?: string;
  title?: string;
  description?: ReactNode;
  /** Every finished test result, and null while untested (the result is stale). */
  onResult?: (result: CheckResult | null) => void;
}) {
  const { config, settings, setSettings, settingsLoaded } = useRunState();
  const [local, setLocal] = useState<{ reachable: boolean; models: string[] } | null>(null);
  const modelListId = useId();

  const provider = providerInfo(settings.model);
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
  const { check, retest } = useModelCheck("tailor", settings, settingsLoaded && !needsKey);
  useEffect(() => {
    if (check !== "testing") onResult?.(check);
    // onResult is a fresh closure each render; only the result matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [check]);
  const modelName = settings.model_name || profileDefaultModel(settings, config);
  const privacy = privacyFor(settings.model, modelName);

  return (
    <Card embedded={embedded} className={className} title={title} description={description}>
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
        {privacy && (
          <p className="mt-3 rounded-sm bg-sunken px-3 py-2 text-xs text-ink-2">
            <span className="font-medium text-ink">Privacy:</span> {privacy}
          </p>
        )}
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

      <ModelCheckRow check={check} provider={provider} needsKey={needsKey} onRetest={retest} />
    </Card>
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
  const name = useId();
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
              name={name}
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
