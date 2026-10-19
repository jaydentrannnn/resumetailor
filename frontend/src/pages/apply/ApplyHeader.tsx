import type { ApplySettings } from "../../api";
import { Button, CommandBar } from "../../components/ui";
import { nightlyRunLabel } from "../../lib/applyPage";
import type { BrowserView } from "../../lib/browserState";
import { ConnectionStatus } from "./BrowserConnection";

/**
 * The Apply page title, with nightly-run state beside the settings action.
 */
export function ApplyHeader({
  apply,
  browser,
  onSettings,
}: {
  apply: Pick<ApplySettings, "enabled" | "schedule_time">;
  browser: BrowserView;
  onSettings: () => void;
}) {
  return (
    <CommandBar
      title="Apply"
      actions={
        <>
          <ConnectionStatus view={browser} />
          <Button
            variant="plain"
            size="sm"
            title="Change the nightly run in Apply settings"
            onClick={onSettings}
          >
            {nightlyRunLabel(apply)}
          </Button>
          <Button size="sm" onClick={onSettings}>
            Apply settings
          </Button>
        </>
      }
    />
  );
}
