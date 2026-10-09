import { useEffect, useState } from "react";
import {
  fetchSetupStatus,
  getBrowserStatus,
  launchBrowser,
  testModel,
  type ApplySettings,
  type BrowserStatus,
  type CheckResult,
} from "../../../api";
import { Button, Card } from "../../../components/ui";
import { browserView } from "../../../lib/browserState";
import { describe } from "../../../lib/errors";
import { SKIP_WARNINGS } from "../../../lib/onboarding";
import { PROVIDERS, providerInfo } from "../../../lib/providers";
import { useRunState } from "../../../state/runState";
import { AutofillModelFields } from "../../apply/AutofillModelFields";
import { BrowserPicker, ConnectionStatus } from "../../apply/BrowserConnection";
import { ApiKeysCard } from "../../settings/ApiKeysCard";
import { CheckResultLine } from "../../settings/CheckResultLine";
import { TailorModelCard } from "../../settings/TailorModelCard";
import { useSecrets } from "../../settings/useSecrets";
import { StepFrame, type StepNav } from "../StepFrame";

/** Keys a model provider reads; job-search keys wait for the Applications page. */
const MODEL_KEYS = [...new Set(PROVIDERS.flatMap((p) => p.keys))];

/** Autofill providers use Anthropic's own name; the key list files it under "claude". */
const autofillKeys = (provider: ApplySettings["model_provider"]) =>
  providerInfo(provider === "anthropic" ? "claude" : provider)?.keys ?? [];

/**
 * Step 2: API keys, then the model that tailors, the model that fills application forms,
 * and the browser Fill opens. Only a working tailoring model is required.
 */
export function ToolsStep({ nav }: { nav: StepNav }) {
  const { settings, setSettings, flushSettings } = useRunState();
  const { secrets, storeBackend, reload } = useSecrets();
  const [tailorOk, setTailorOk] = useState(false);
  const [autofill, setAutofill] = useState<CheckResult | null>(null);
  const [testingAutofill, setTestingAutofill] = useState(false);
  const [browser, setBrowser] = useState<BrowserStatus | null>(null);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const apply = settings.apply;
  const patch = (fields: Partial<ApplySettings>) => {
    setSettings({ ...settings, apply: { ...apply, ...fields } });
    if ("model_provider" in fields || "model_name" in fields) setAutofill(null);
  };

  useEffect(() => {
    // A model that already answers (set up before, or tested on an earlier visit) counts.
    fetchSetupStatus()
      .then((s) => s.items.find((i) => i.id === "model")?.ok && setTailorOk(true))
      .catch(() => undefined);
    getBrowserStatus()
      .then(setBrowser)
      .catch(() => undefined);
  }, []);

  async function testAutofill() {
    setTestingAutofill(true);
    setAutofill(null);
    try {
      await flushSettings();
      setAutofill(await testModel(settings, "autofill"));
    } catch (err) {
      setAutofill({ ok: false, detail: describe(err).detail });
    } finally {
      setTestingAutofill(false);
    }
  }

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
  const highlighted = [
    ...(providerInfo(settings.model)?.keys ?? []),
    ...autofillKeys(apply.model_provider),
  ];

  return (
    <StepFrame
      title="AI & browser"
      intro="Add any API keys first, then pick the model that tailors your resume and the one that fills in application forms."
      nav={nav}
      complete={tailorOk}
      onSave={save}
      skipWarning={SKIP_WARNINGS.tools}
      error={error}
    >
      <ApiKeysCard
        embedded
        secrets={secrets}
        storeBackend={storeBackend}
        reload={reload}
        highlighted={highlighted}
        only={MODEL_KEYS}
      />
      <TailorModelCard
        embedded
        className="border-t border-line pt-4"
        secrets={secrets}
        title="Tailoring model"
        description="Rewrites your bullets for each job in many small steps. A lightweight model is plenty and saves usage; leave the model blank for the default (gemma4:cloud on Ollama). Run the test to continue."
        onResult={(result) => setTailorOk(!!result?.ok)}
      />
      <Card
        embedded
        className="border-t border-line pt-4"
        title="Autofill model"
        description="Reads application forms and writes answers to their questions. A mid-tier model does noticeably better here than a lightweight one."
      >
        <AutofillModelFields apply={apply} patch={patch} />
        <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 text-sm text-ink-muted">
            {autofill ? <CheckResultLine result={autofill} /> : "Optional: check it answers."}
          </div>
          <Button variant="secondary" loading={testingAutofill} onClick={() => void testAutofill()}>
            Test connection
          </Button>
        </div>
      </Card>
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
