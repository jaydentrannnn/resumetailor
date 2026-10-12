import type { SecretState } from "../../api";
import { useRunState } from "../../state/runState";
import { ApiKeysCard } from "./ApiKeysCard";
import { KeyRow } from "./KeyRow";
import type { ModelCheck } from "./useModelCheck";
import type { RoleModel } from "./useRoleModel";

/**
 * Every API key in one list, the chosen models' keys highlighted with their test status,
 * and a block per role that uses a custom server (format, URL and its own key) on top.
 */
export function ModelKeysCard({
  models,
  secrets,
  storeBackend,
  reload,
  onlyNeeded = false,
  embedded,
  className,
}: {
  models: RoleModel[];
  secrets: SecretState[];
  storeBackend: string;
  reload: () => void;
  /** List only the keys the chosen providers need (the setup wizard). */
  onlyNeeded?: boolean;
  embedded?: boolean;
  className?: string;
}) {
  const custom = models.filter((m) => m.selection.provider === "custom");
  const named = models.filter((m) => m.selection.provider !== "custom");
  const needed = named.flatMap((m) => m.connection.keys.map((key) => key.name));
  const checks: Record<string, ModelCheck> = {};
  // A failure on either model wins, so a key that works for one but not the other shows it.
  for (const m of named)
    for (const key of m.connection.keys)
      if (!checks[key.name] || (m.check && m.check !== "testing" && !m.check.ok))
        checks[key.name] = m.check;
  if (onlyNeeded && !needed.length && !custom.length) return null;
  // A needed key is listed even before the server reports its slot.
  const missing = named
    .flatMap((m) => m.connection.keys)
    .filter(
      (key, i, all) =>
        !secrets.some((s) => s.name === key.name) &&
        all.findIndex((k) => k.name === key.name) === i,
    );
  return (
    <ApiKeysCard
      embedded={embedded}
      className={className}
      secrets={[...missing, ...secrets]}
      storeBackend={storeBackend}
      reload={reload}
      highlighted={needed}
      checks={checks}
      only={onlyNeeded ? needed : undefined}
      before={custom.map((m) => (
        <CustomServerBlock key={m.role} model={m} reload={reload} />
      ))}
    />
  );
}

/** A custom server's API format, URL and optional key — the key is bound to all three. */
function CustomServerBlock({ model, reload }: { model: RoleModel; reload: () => void }) {
  const { settingsLoaded } = useRunState();
  const { role, selection, connection, check, patch } = model;
  const name = `Custom server (${role === "light" ? "Light" : "Heavy"})`;
  return (
    <li className="min-w-0 py-4 first:pt-0 last:pb-0">
      <fieldset disabled={!settingsLoaded} className="min-w-0 space-y-3">
        <legend className="text-sm font-medium text-accent">{name}</legend>
        <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)]">
          <label className="block min-w-0 text-sm font-medium">
            API format
            <select
              className="field mt-1"
              value={selection.api_format}
              onChange={(e) => patch({ api_format: e.target.value as typeof selection.api_format })}
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
        </div>
        {connection.keys.length ? (
          <ul>
            {connection.keys.map((key) => (
              <KeyRow
                key={key.name}
                secret={key}
                highlighted
                check={check}
                onChange={reload}
                label="Server API key (optional)"
              />
            ))}
          </ul>
        ) : (
          <p className="text-xs text-ink-muted">Enter a server URL to add its API key.</p>
        )}
      </fieldset>
    </li>
  );
}
