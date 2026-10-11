import { modelsFor, selectionProvider } from "../../lib/aiModels";
import { Card } from "../../components/ui";
import { useRunState } from "../../state/runState";
import { AiAdvancedCard } from "./AiAdvancedCard";
import { ApiKeysCard } from "./ApiKeysCard";
import { AutofillModelCard } from "./AutofillModelCard";
import { TailorModelCard } from "./TailorModelCard";
import { UsageCard } from "./UsageCard";
import { useSecrets } from "./useSecrets";

export function AiSection() {
  const { settings, settingsLoaded } = useRunState();
  const { secrets, storeBackend, reload } = useSecrets();
  const models = modelsFor(settings);
  const selectedKeys = new Set([
    ...(selectionProvider(models.light)?.keys ?? []),
    ...(selectionProvider(models.heavy)?.keys ?? []),
  ]);
  return (
    <div className="space-y-4">
      <TailorModelCard secrets={secrets} reload={reload} />
      <AutofillModelCard secrets={secrets} reload={reload} />
      <Card
        title="Other API keys"
        description="Saved credentials for other providers and job-search services."
      >
        <details>
          <summary className="cursor-pointer text-sm font-medium">Manage other keys</summary>
          {settingsLoaded && (
            <div className="mt-4">
              <ApiKeysCard
                embedded
                secrets={secrets.filter(
                  (secret) => !secret.name.startsWith("CUSTOM_") && !selectedKeys.has(secret.name),
                )}
                storeBackend={storeBackend}
                reload={reload}
                highlighted={[]}
              />
            </div>
          )}
        </details>
      </Card>
      <AiAdvancedCard />
      <UsageCard />
    </div>
  );
}
