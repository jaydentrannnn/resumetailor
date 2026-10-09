import { Button } from "../../components/ui";
import type { ProviderInfo } from "../../lib/providers";
import { CheckResultLine } from "./CheckResultLine";
import { SettingRow } from "./SettingRow";
import type { ModelCheck } from "./useModelCheck";

/** The automatic connection test's outcome, with a Retest and the provider's link. */
export function ModelCheckRow({
  check,
  provider,
  needsKey,
  onRetest,
}: {
  check: ModelCheck;
  provider: ProviderInfo | undefined;
  needsKey: boolean;
  onRetest: () => void;
}) {
  let status;
  if (needsKey) status = `${provider?.name ?? "This provider"} needs an API key. Add it below.`;
  else if (check === "testing") status = <span role="status">Testing the connection…</span>;
  else if (check) status = <CheckResultLine result={check} />;
  else status = "Checks automatically when you pick a provider or model.";
  return (
    <div className="mt-4 border-t border-line pt-4">
      <SettingRow label="Connection" layout="action" description={status}>
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {provider?.link && (
            <a
              className="rt-link text-sm font-medium"
              href={provider.link.href}
              target="_blank"
              rel="noreferrer"
            >
              {provider.link.label}
            </a>
          )}
          <Button
            size="sm"
            variant="plain"
            disabled={needsKey}
            loading={check === "testing"}
            onClick={onRetest}
          >
            Test again
          </Button>
        </div>
      </SettingRow>
    </div>
  );
}
