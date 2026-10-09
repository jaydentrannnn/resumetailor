import { providerInfo } from "../../lib/providers";
import { useRunState } from "../../state/runState";
import { ApiKeysCard } from "./ApiKeysCard";
import { TailorModelCard } from "./TailorModelCard";
import { useSecrets } from "./useSecrets";

/** Settings → Models: which AI to use, its keys, and a live connection test. */
export function ModelsSection() {
  const { settings } = useRunState();
  const { secrets, storeBackend, reload } = useSecrets();
  return (
    <div className="space-y-4">
      <TailorModelCard secrets={secrets} />
      <ApiKeysCard
        secrets={secrets}
        storeBackend={storeBackend}
        reload={reload}
        highlighted={providerInfo(settings.model)?.keys ?? []}
      />
    </div>
  );
}
