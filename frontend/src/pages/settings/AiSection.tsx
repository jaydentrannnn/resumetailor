import type { SecretState } from "../../api";
import { autofillProviderId, providerInfo } from "../../lib/providers";
import { useRunState } from "../../state/runState";
import { AiAdvancedCard } from "./AiAdvancedCard";
import { ApiKeysCard } from "./ApiKeysCard";
import { AutofillModelCard } from "./AutofillModelCard";
import { TailorModelCard } from "./TailorModelCard";
import { UsageCard } from "./UsageCard";
import { useModelCheck, type ModelCheck } from "./useModelCheck";
import { useSecrets } from "./useSecrets";

function keyed(keys: string[], secrets: SecretState[]) {
  const set = keys.filter((k) => secrets.some((s) => s.name === k && s.set));
  return { keys: set, needsKey: keys.length > 0 && set.length === 0 };
}

/** A failure on either model wins, so a key that works for one but not the other shows it. */
function merge(into: Record<string, ModelCheck>, keys: string[], check: ModelCheck) {
  for (const key of keys) {
    const current = into[key];
    if (!current || (check && check !== "testing" && !check.ok)) into[key] = check;
  }
}

/** Settings → AI: both models, their keys (with live test status), usage, advanced. */
export function AiSection() {
  const { settings, settingsLoaded } = useRunState();
  const { secrets, storeBackend, reload } = useSecrets();
  const tailorKeys = providerInfo(settings.model)?.keys ?? [];
  const autofillKeys = providerInfo(autofillProviderId(settings.apply.model_provider))?.keys ?? [];
  const tailor = keyed(tailorKeys, secrets);
  const autofill = keyed(autofillKeys, secrets);
  // Same cache and in-flight call as the cards' own checks: no extra requests.
  const tailorCheck = useModelCheck("tailor", settings, settingsLoaded && !tailor.needsKey);
  const autofillCheck = useModelCheck(
    "autofill",
    settings,
    settingsLoaded && !autofill.needsKey && !!settings.apply.model_name.trim(),
  );
  const checks: Record<string, ModelCheck> = {};
  merge(checks, tailor.keys, tailorCheck.check);
  merge(checks, autofill.keys, autofillCheck.check);
  return (
    <div className="space-y-4">
      <TailorModelCard secrets={secrets} />
      <AutofillModelCard secrets={secrets} />
      <ApiKeysCard
        secrets={secrets}
        storeBackend={storeBackend}
        reload={reload}
        highlighted={[...tailorKeys, ...autofillKeys]}
        checks={checks}
      />
      <UsageCard />
      <AiAdvancedCard />
    </div>
  );
}
