import { useId } from "react";
import { Button, StatusChip } from "../../components/ui";
import { modelsFor, selectionDefault, type ModelProvider } from "../../lib/aiModels";
import { PROVIDERS, privacyFor, providerInfo } from "../../lib/providers";
import { useRunState } from "../../state/runState";
import { CheckResultLine } from "./CheckResultLine";
import type { RoleModel } from "./useRoleModel";

const ROLES = {
  light: { name: "Light task model", uses: "Tailoring, cover letters, extraction and app tools." },
  heavy: { name: "Heavy task model", uses: "Application answers and AI-assisted form filling." },
} as const;

const LOCAL_PRIVACY = providerInfo("ollama")?.privacy;

/** One role's provider and model, with its automatic connection test. */
export function ModelRow({ model }: { model: RoleModel }) {
  const { settings, config } = useRunState();
  const { role, selection, connection, patch } = model;
  const id = useId();
  const fallback = selectionDefault(selection, config);
  const privacy = privacyFor(
    selection.provider === "anthropic" ? "claude" : selection.provider,
    selection.model_name || fallback,
  );
  const models = connection.local?.models ?? [];
  return (
    <div role="group" aria-labelledby={`${id}-name`} className="min-w-0 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h3 id={`${id}-name`} className="text-sm font-semibold text-ink">
            {ROLES[role].name}
          </h3>
          <p className="text-xs text-ink-muted">{ROLES[role].uses}</p>
        </div>
        <RowStatus model={model} />
      </div>
      <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
        <label className="block min-w-0 text-sm font-medium">
          Provider
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
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id === "claude" ? "anthropic" : p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block min-w-0 text-sm font-medium">
          Model
          <input
            className="field mt-1 font-mono"
            value={selection.model_name}
            placeholder={fallback}
            list={models.length ? `${id}-models` : undefined}
            onChange={(e) => patch({ model_name: e.target.value })}
          />
          {models.length > 0 && (
            <datalist id={`${id}-models`}>
              {models.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          )}
        </label>
      </div>
      <RowNotes model={model} />
      {privacy && privacy !== LOCAL_PRIVACY && (
        <p className="mt-2 text-xs text-ink-muted">{privacy}</p>
      )}
      {role === "light" && Object.keys(modelsFor(settings).legacy_light_overrides).length > 0 && (
        <p className="mt-2 text-xs text-ink-muted">
          Existing stage overrides are preserved until you edit this model.
        </p>
      )}
    </div>
  );
}

/** The test result as a chip, with Test again once the model can be tested. */
function RowStatus({ model }: { model: RoleModel }) {
  const { check, ready, connection, retest } = model;
  let chip;
  if (connection.needsKey) chip = <StatusChip tone="attention">Needs a key</StatusChip>;
  else if (!ready) chip = <StatusChip tone="muted">Incomplete</StatusChip>;
  else if (check === "testing") chip = <StatusChip tone="live">Testing…</StatusChip>;
  else if (check?.ok) chip = <StatusChip tone="done">Working</StatusChip>;
  else if (check) chip = <StatusChip tone="failed">Not working</StatusChip>;
  return (
    <div className="flex items-center gap-2">
      {chip}
      {ready && !connection.needsKey && (
        <Button size="sm" variant="plain" loading={check === "testing"} onClick={retest}>
          Test again
        </Button>
      )}
    </div>
  );
}

/** What to do next: the failure, a missing key or URL, or a local app that is not running. */
function RowNotes({ model }: { model: RoleModel }) {
  const { selection, connection, check } = model;
  const provider = connection.provider;
  const link = provider?.link && (
    <a className="rt-link" href={provider.link.href} target="_blank" rel="noreferrer">
      {provider.link.label}
    </a>
  );
  if (connection.needsKey)
    return (
      <p className="mt-2 text-xs text-ink-muted">
        Add your {provider?.name ?? "provider"} key under API keys below. {link}
      </p>
    );
  if (selection.provider === "custom" && !selection.base_url.trim())
    return (
      <p className="mt-2 text-xs text-ink-muted">Enter the server URL under API keys below.</p>
    );
  if (connection.local && !connection.local.reachable)
    return (
      <p className="mt-2 text-xs text-ink-muted">
        {provider?.name} is not running, so installed models cannot be listed. {link}
      </p>
    );
  if (check && check !== "testing" && !check.ok) return <CheckResultLine result={check} />;
  return null;
}
