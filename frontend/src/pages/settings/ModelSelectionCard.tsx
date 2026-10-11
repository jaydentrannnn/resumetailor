import { useEffect, useId, type ReactNode } from "react";
import type { CheckResult, SecretState } from "../../api";
import { Card } from "../../components/ui";
import {
  modelsFor,
  selectionDefault,
  selectionReady,
  withSelection,
  type ModelProvider,
  type ModelRole,
  type ModelSelection,
} from "../../lib/aiModels";
import { PROVIDERS, privacyFor } from "../../lib/providers";
import { useRunState } from "../../state/runState";
import { KeyRow } from "./KeyRow";
import { ModelCheckRow } from "./ModelCheckRow";
import { useModelCheck } from "./useModelCheck";
import { useModelConnection } from "./useModelConnection";

export type ModelCardProps = {
  secrets: SecretState[];
  reload?: () => void;
  embedded?: boolean;
  className?: string;
  description?: ReactNode;
  onResult?: (result: CheckResult | null) => void;
  title?: string;
};

export function ModelSelectionCard({
  role,
  secrets,
  reload = () => {},
  embedded = false,
  className = "",
  description,
  onResult,
  title,
}: ModelCardProps & { role: ModelRole }) {
  const { settings, config, setSettings, settingsLoaded } = useRunState();
  const models = modelsFor(settings);
  const selection = models[role];
  const connection = useModelConnection(role, selection, secrets);
  const listId = useId();
  const ready = selectionReady(selection);
  const { check, retest } = useModelCheck(
    role,
    settings,
    settingsLoaded && ready && !connection.needsKey,
  );
  useEffect(() => {
    if (check !== "testing") onResult?.(check);
  }, [check, onResult]);
  const patch = (fields: Partial<ModelSelection>) =>
    setSettings(withSelection(settings, role, { ...selection, ...fields }));
  const privacy = privacyFor(
    selection.provider === "anthropic" ? "claude" : selection.provider,
    selection.model_name,
  );
  return (
    <Card
      embedded={embedded}
      className={className}
      title={title ?? `${role === "light" ? "Light" : "Heavy"} task model`}
      description={
        description ??
        (role === "light"
          ? "Used for tailoring, cover letters, extraction, skills, and app tools."
          : "Used for application answers and AI-assisted form filling.")
      }
    >
      <fieldset disabled={!settingsLoaded} className="grid min-w-0 gap-4 sm:grid-cols-2">
        <label className="block text-sm font-medium">
          <span className="rt-model-label">Provider</span>
          <select
            className="field mt-1"
            value={selection.provider}
            onChange={(e) =>
              patch({
                provider: e.target.value as ModelProvider,
                model_name: "",
                base_url: "",
                api_format: "openai",
              })
            }
          >
            {PROVIDERS.map((provider) => (
              <option
                key={provider.id}
                value={provider.id === "claude" ? "anthropic" : provider.id}
              >
                {provider.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium">
          <span className="rt-model-label">Model</span>
          <input
            aria-label="Model"
            aria-describedby={`${listId}-hint`}
            className="field mt-1 font-mono"
            value={selection.model_name}
            placeholder={selectionDefault(selection, config)}
            list={connection.local?.models.length ? listId : undefined}
            onChange={(e) => patch({ model_name: e.target.value })}
          />
          {connection.local?.models.length ? (
            <datalist id={listId}>
              {connection.local.models.map((model) => (
                <option key={model} value={model} />
              ))}
            </datalist>
          ) : null}
          <span id={`${listId}-hint`} className="mt-1 block text-xs font-normal text-ink-muted">
            {selection.provider === "custom" || selection.provider === "openai"
              ? "Enter the exact model name supplied by the provider."
              : "Leave blank for the default model."}
          </span>
        </label>
        {selection.provider === "custom" && (
          <>
            <label className="block text-sm font-medium">
              API format
              <select
                className="field mt-1"
                value={selection.api_format}
                onChange={(e) =>
                  patch({ api_format: e.target.value as ModelSelection["api_format"] })
                }
              >
                <option value="openai">OpenAI-compatible</option>
                <option value="anthropic">Anthropic-compatible</option>
              </select>
            </label>
            <label className="block min-w-0 text-sm font-medium">
              Server URL
              <input
                className="field mt-1 font-mono"
                type="url"
                value={selection.base_url}
                placeholder={
                  selection.api_format === "openai"
                    ? "https://server.example/v1"
                    : "https://server.example"
                }
                onChange={(e) => patch({ base_url: e.target.value })}
              />
            </label>
          </>
        )}
      </fieldset>
      {connection.local && !connection.local.reachable && (
        <p className="mt-2 text-xs text-ink-muted">
          {connection.provider?.name} is not running, so installed models cannot be listed.
        </p>
      )}
      {privacy && (
        <p className="mt-3 rounded-sm bg-sunken px-3 py-2 text-xs text-ink-2">{privacy}</p>
      )}
      {role === "light" && Object.keys(models.legacy_light_overrides).length > 0 && (
        <p className="mt-2 text-xs text-ink-muted">
          Existing stage overrides are preserved until you edit this model.
        </p>
      )}
      {!!connection.keys.length && (
        <ul className="mt-4 border-t border-line pt-4">
          {connection.keys.map((key) => (
            <KeyRow
              key={key.name}
              secret={key}
              highlighted
              check={check}
              onChange={reload}
              label={selection.provider === "custom" ? "Server API key (optional)" : undefined}
            />
          ))}
        </ul>
      )}
      {selection.provider === "custom" && !selection.base_url && (
        <p className="mt-2 text-xs text-ink-muted">Enter a server URL to configure its API key.</p>
      )}
      <ModelCheckRow
        check={check}
        provider={connection.provider}
        needsKey={connection.needsKey}
        disabled={!ready || !settingsLoaded}
        onRetest={retest}
      />
    </Card>
  );
}
