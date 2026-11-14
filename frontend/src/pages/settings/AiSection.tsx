import { FullOnly } from "../../components/FullOnly";
import { useUiMode } from "../../lib/uiMode";
import { useRunState } from "../../state/runState";
import { ModelKeysCard } from "./ModelKeysCard";
import { ModelsCard } from "./ModelsCard";
import { UsageCard } from "./UsageCard";
import { useRoleModel } from "./useRoleModel";
import { useSecrets } from "./useSecrets";

/** Settings → AI: one tile for both models (Advanced inside it), every API key, usage. */
export function AiSection() {
  const { settings, settingsLoaded } = useRunState();
  // Simple view: no Advanced switch (unless it is on) and no usage card.
  const { simple } = useUiMode();
  const { secrets, storeBackend, reload } = useSecrets();
  const light = useRoleModel("light", secrets);
  const heavy = useRoleModel("heavy", secrets);
  return (
    <div className="space-y-10">
      <ModelsCard
        light={light}
        heavy={heavy}
        advanced={!simple || settings.ai_advanced_enabled === true}
      />
      {settingsLoaded && (
        <ModelKeysCard
          models={[light, heavy]}
          secrets={secrets}
          storeBackend={storeBackend}
          reload={reload}
          onlyNeeded={simple}
          keepSet
        />
      )}
      <FullOnly>
        <UsageCard />
      </FullOnly>
    </div>
  );
}
