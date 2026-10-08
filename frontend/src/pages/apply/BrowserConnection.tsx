import { useState } from "react";
import { CopyButton } from "../../components/CopyButton";
import { StatusChip, Tabs } from "../../components/ui";
import {
  BROWSER_DEBUG_COMMANDS,
  BROWSER_TARGET_LABELS,
  defaultTarget,
  type BrowserTarget,
} from "../../lib/browserCommand";

/** Browser reachability as a status chip: a check when connected, a ring when it needs you. */
export function ConnectionStatus({ connected }: { connected: boolean }) {
  return (
    <StatusChip tone={connected ? "done" : "attention"}>
      {connected ? "Browser connected" : "Browser not connected"}
    </StatusChip>
  );
}

/** The remote-debugging command for the selected browser/OS. */
export function BrowserCommand() {
  const [target, setTarget] = useState<BrowserTarget>(() => defaultTarget());
  const { browser, shell, command } = BROWSER_DEBUG_COMMANDS[target];
  return (
    <>
      <div className="mt-2">
        <Tabs
          label="Operating system and browser"
          variant="segmented"
          items={(Object.keys(BROWSER_TARGET_LABELS) as BrowserTarget[]).map((key) => ({
            id: key,
            label: BROWSER_TARGET_LABELS[key],
          }))}
          value={target}
          onChange={(id) => setTarget(id as BrowserTarget)}
        />
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        For browser-assisted Fill, run this in {shell} to start {browser} with remote debugging on
        port 9222, then check the connection. Keep the browser open while reviewing forms, and use
        this {browser} profile only for job-site logins.
      </p>
      <div className="mt-2 flex items-start gap-2">
        <code className="min-w-0 flex-1 rounded-sm border border-line bg-field px-3 py-2 font-mono text-xs [overflow-wrap:anywhere]">
          {command}
        </code>
        <CopyButton label="Copy command" text={command} />
      </div>
    </>
  );
}
