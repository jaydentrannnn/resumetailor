import { useRunState } from "../../state/runState";
import { AiAdvancedCard } from "./AiAdvancedCard";
import { ModelKeysCard } from "./ModelKeysCard";
import { ModelsCard } from "./ModelsCard";
import { UsageCard } from "./UsageCard";
import { useRoleModel } from "./useRoleModel";
import { useSecrets } from "./useSecrets";

/** Settings → AI: one tile for both models, every API key in one list, advanced, usage. */
export function AiSection() {
  const { settingsLoaded } = useRunState();
  const { secrets, storeBackend, reload } = useSecrets();
  const light = useRoleModel("light", secrets);
  const heavy = useRoleModel("heavy", secrets);
  return (
    <div className="space-y-4">
      <ModelsCard light={light} heavy={heavy} />
      {settingsLoaded && (
        <ModelKeysCard
          models={[light, heavy]}
          secrets={secrets}
          storeBackend={storeBackend}
          reload={reload}
        />
      )}
      <AiAdvancedCard />
      <UsageCard />
    </div>
  );
}
