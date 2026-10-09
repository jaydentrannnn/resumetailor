import type { ApplySettings } from "../../api";
import { Button, PageHeader } from "../../components/ui";
import { nightlyRunLabel } from "../../lib/applyPage";
import { ConnectionStatus } from "./BrowserConnection";

/**
 * The Apply page title, with nightly-run state beside the settings action.
 */
export function ApplyHeader({
  apply,
  browserConnected,
  onSettings,
}: {
  apply: Pick<ApplySettings, "enabled" | "schedule_time">;
  browserConnected: boolean;
  onSettings: () => void;
}) {
  return (
    <PageHeader
      title="Apply"
      description="Postings from your job sources, each prepared with its own tailored resume."
      actions={
        <>
          <ConnectionStatus connected={browserConnected} />
          <Button
            variant="outline"
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
