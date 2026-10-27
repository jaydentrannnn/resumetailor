import type { ApplySettings } from "../../api";
import { Link } from "react-router-dom";
import { AutomationSwitch } from "../../components/AutomationSwitch";
import { Button, buttonClass, CommandBar } from "../../components/ui";
import { nightlyRunLabel, SOURCES_PATH } from "../../lib/applyPage";
import type { BrowserView } from "../../lib/browserState";
import { ConnectionStatus } from "./BrowserConnection";
import type { PollSync } from "./useApplyOperation";

/**
 * The Apply page title, with Pause automation, Job sources and the nightly-run state
 * beside the settings action. While the app cannot be reached it says so, with the
 * time the list was last up to date.
 */
export function ApplyHeader({
  apply,
  browser,
  sync,
  onSettings,
}: {
  apply: Pick<ApplySettings, "enabled" | "schedule_time">;
  browser: BrowserView;
  sync?: PollSync;
  onSettings: () => void;
}) {
  return (
    <CommandBar
      title="Apply"
      state={
        sync?.reconnecting && (
          <span role="status" className="text-attn">
            Reconnecting…
            {sync.updatedAt
              ? ` · updated ${new Date(sync.updatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
              : ""}
          </span>
        )
      }
      actions={
        <>
          <ConnectionStatus view={browser} />
          <AutomationSwitch />
          <Link className={buttonClass("plain", "sm")} to={SOURCES_PATH}>
            Job sources
          </Link>
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
