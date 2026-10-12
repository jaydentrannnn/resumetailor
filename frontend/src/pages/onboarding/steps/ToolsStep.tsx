import { useEffect, useState } from "react";
import {
  fetchSetupStatus,
  getBrowserStatus,
  launchBrowser,
  type ApplySettings,
  type BrowserStatus,
} from "../../../api";
import { Card } from "../../../components/ui";
import { browserView } from "../../../lib/browserState";
import { describe } from "../../../lib/errors";
import { SKIP_WARNINGS } from "../../../lib/onboarding";
import { useRunState } from "../../../state/runState";
import { BrowserPicker, ConnectionStatus } from "../../apply/BrowserConnection";
import { ModelKeysCard } from "../../settings/ModelKeysCard";
import { ModelsCard } from "../../settings/ModelsCard";
import { useRoleModel } from "../../settings/useRoleModel";
import { useSecrets } from "../../settings/useSecrets";
import { StepFrame, type StepNav } from "../StepFrame";

/**
 * Step 2: API keys, then the model that tailors, the model that fills application forms,
 * and the browser Fill opens. Only a working tailoring model is required.
 */
export function ToolsStep({ nav }: { nav: StepNav }) {
  const { settings, setSettings, flushSettings, settingsLoaded } = useRunState();
  const { secrets, storeBackend, reload } = useSecrets();
  const light = useRoleModel("light", secrets);
  const heavy = useRoleModel("heavy", secrets);
  const [tailorOk, setTailorOk] = useState(false);
  const [browser, setBrowser] = useState<BrowserStatus | null>(null);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const apply = settings.apply;
  const patch = (fields: Partial<ApplySettings>) =>
    setSettings({ ...settings, apply: { ...apply, ...fields } });

  useEffect(() => {
    // A model that already answers (set up before, or tested on an earlier visit) counts.
    fetchSetupStatus()
      .then((s) => s.items.find((i) => i.id === "model")?.ok && setTailorOk(true))
      .catch(() => undefined);
    getBrowserStatus()
      .then(setBrowser)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (light.check !== "testing") setTailorOk(!!light.check?.ok);
  }, [light.check]);

  async function launch() {
    setLaunching(true);
    try {
      await flushSettings();
      setBrowser(await launchBrowser());
    } catch (err) {
      setError(describe(err).detail);
    } finally {
      setLaunching(false);
    }
  }

  async function save() {
    setError(null);
    if (await flushSettings()) return true;
    setError("Could not save these settings. Try again.");
    return false;
  }

  const view = browserView(browser, apply.browser ?? null);
  return (
    <StepFrame
      title="AI & browser"
      intro="Choose the light model for tailoring and app tools, and the heavy model for application answers and form filling."
      nav={nav}
      complete={tailorOk}
      onSave={save}
      skipWarning={SKIP_WARNINGS.tools}
      error={error}
    >
      <ModelsCard
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
      <Card
        embedded
        className="border-t border-line pt-4"
        title="Browser"
        description="The browser autofill opens to fill in applications."
        actions={<ConnectionStatus view={view} />}
      >
        <BrowserPicker
          status={browser}
          view={view}
          selected={apply.browser ?? null}
          onSelect={(id) => patch({ browser: id })}
          launch={{ run: () => void launch(), busy: launching }}
        />
      </Card>
    </StepFrame>
  );
}
