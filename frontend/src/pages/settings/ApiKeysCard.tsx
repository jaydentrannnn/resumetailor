import type { SecretState } from "../../api";
import { Card } from "../../components/ui";
import { KeyRow } from "./KeyRow";
import type { ModelCheck } from "./useModelCheck";

/** Every API key the app can use; the ones the chosen providers need are highlighted. */
export function ApiKeysCard({
  secrets,
  storeBackend,
  reload,
  highlighted,
  embedded = false,
  className = "",
  only,
  checks = {},
}: {
  secrets: SecretState[];
  storeBackend: string;
  reload: () => void;
  highlighted: string[];
  embedded?: boolean;
  className?: string;
  /** Show just these key names (the setup wizard lists model keys only). */
  only?: string[];
  /** Connection-test status per key name, for the models that use it. */
  checks?: Record<string, ModelCheck>;
}) {
  return (
    <Card
      embedded={embedded}
      className={className}
      title="API keys"
      description={
        storeBackend === "keyring"
          ? "Saved in your system keychain, never in plain files. Keys set in a .env file take priority."
          : "Saved encrypted in your data folder. Keys set in a .env file take priority."
      }
    >
      <ul className="divide-y divide-line">
        {secrets
          .filter((secret) => !only || only.includes(secret.name))
          .map((secret) => (
            <KeyRow
              key={secret.name}
              secret={secret}
              highlighted={highlighted.includes(secret.name)}
              check={checks[secret.name] ?? null}
              onChange={reload}
            />
          ))}
      </ul>
    </Card>
  );
}
