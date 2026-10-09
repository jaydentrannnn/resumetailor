import type { ReactNode } from "react";
import type { SecretState } from "../../api";
import { Card } from "../../components/ui";
import { autofillProviderId, privacyFor, providerInfo } from "../../lib/providers";
import { useRunState } from "../../state/runState";
import { AutofillModelFields } from "../apply/AutofillModelFields";
import { ModelCheckRow } from "./ModelCheckRow";
import { useModelCheck } from "./useModelCheck";

/** The Autofill model (Apply's form answers), tested automatically like the Tailor one. */
export function AutofillModelCard({
  secrets,
  embedded = false,
  className = "",
  description = "Reads application forms and writes answers to their questions. A mid-tier model does noticeably better here than a lightweight one.",
}: {
  secrets: SecretState[];
  embedded?: boolean;
  className?: string;
  description?: ReactNode;
}) {
  const { settings, setSettings, settingsLoaded } = useRunState();
  const apply = settings.apply;
  const provider = providerInfo(autofillProviderId(apply.model_provider));
  const needsKey = provider?.keys.length
    ? !secrets.some((s) => provider.keys.includes(s.name) && s.set)
    : false;
  const { check, retest } = useModelCheck(
    "autofill",
    settings,
    settingsLoaded && !needsKey && !!apply.model_name.trim(),
  );
  const privacy = privacyFor(autofillProviderId(apply.model_provider), apply.model_name);
  return (
    <Card
      embedded={embedded}
      className={className}
      title="Autofill model"
      description={description}
    >
      <AutofillModelFields
        apply={apply}
        patch={(fields) => setSettings({ ...settings, apply: { ...apply, ...fields } })}
      />
      {privacy && (
        <p className="mt-3 rounded-sm bg-sunken px-3 py-2 text-xs text-ink-2">
          <span className="font-medium text-ink">Privacy:</span> {privacy}
          {privacy !== provider?.privacy || !provider?.local ? " Form questions are sent too." : ""}
        </p>
      )}
      <ModelCheckRow check={check} provider={provider} needsKey={needsKey} onRetest={retest} />
    </Card>
  );
}
