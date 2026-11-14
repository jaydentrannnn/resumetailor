import { useEffect, useState } from "react";
import { fetchSetupStatus } from "../../../api";
import { SKIP_WARNINGS } from "../../../lib/onboarding";
import { useRunState } from "../../../state/runState";
import { ModelKeysCard } from "../../settings/ModelKeysCard";
import { ModelsCard } from "../../settings/ModelsCard";
import { useRoleModel } from "../../settings/useRoleModel";
import { useSecrets } from "../../settings/useSecrets";
import { StepFrame, type StepNav } from "../StepFrame";

/**
 * The last step before the app opens: API keys, then the model that tailors and the model
 * that fills application forms. Only a working tailoring model is required.
 */
export function ToolsStep({ nav }: { nav: StepNav }) {
  const { flushSettings, settingsLoaded } = useRunState();
  const { secrets, storeBackend, reload } = useSecrets();
  const light = useRoleModel("light", secrets);
  const heavy = useRoleModel("heavy", secrets);
  const [tailorOk, setTailorOk] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // A model that already answers (set up before, or tested on an earlier visit) counts.
    fetchSetupStatus()
      .then((s) => s.items.find((i) => i.id === "model")?.ok && setTailorOk(true))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (light.check !== "testing") setTailorOk(!!light.check?.ok);
  }, [light.check]);

  async function save() {
    setError(null);
    if (await flushSettings()) return true;
    setError("Could not save these settings. Try again.");
    return false;
  }

  return (
    <StepFrame
      title="AI model"
      intro="Choose the light model for tailoring and app tools, and the heavy model for application answers and form filling."
      nav={nav}
      complete={tailorOk}
      onSave={save}
      skipWarning={SKIP_WARNINGS.tools}
      nextLabel={nav.finishes ? "Open the app" : undefined}
      error={error}
    >
      <ModelsCard
        deferHeavy
        embedded
        className="border-t border-line pt-4"
        light={light}
        heavy={heavy}
        description="The light model rewrites your bullets for each job in many small steps; a lightweight one is plenty and saves usage. Leave its model blank for the default (gemma4:cloud on Ollama). The heavy model answers application questions. Both are tested automatically; continue once the light model works."
      />
      {settingsLoaded && (
        <ModelKeysCard
          embedded
          className="border-t border-line pt-4"
          models={[light, heavy]}
          secrets={secrets}
          storeBackend={storeBackend}
          reload={reload}
          onlyNeeded
        />
      )}
    </StepFrame>
  );
}
