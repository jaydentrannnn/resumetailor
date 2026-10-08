import type { ApplySettings } from "../../api";
import { Button, PageHeader } from "../../components/ui";
import { nightlyRunLabel } from "../../lib/applyPage";
import { ConnectionStatus } from "./BrowserConnection";

/**
 * The Apply page title. The eyebrow is the nightly-run state; it and "Apply settings"
 * both open the settings drawer.
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
      eyebrow={
        <button
          type="button"
          className="rt-eyebrow hover:text-ink"
          title="Change the nightly run in Apply settings"
          onClick={onSettings}
        >
          {nightlyRunLabel(apply)}
        </button>
      }
      title="Apply"
      description="Postings from your job sources, each prepared with its own tailored resume."
      actions={
        <>
          <ConnectionStatus connected={browserConnected} />
          <Button size="sm" onClick={onSettings}>
            Apply settings
          </Button>
        </>
      }
    />
  );
}
