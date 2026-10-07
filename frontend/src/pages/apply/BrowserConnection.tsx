import { useState } from "react";
import { CopyButton } from "../../components/CopyButton";
import {
  BROWSER_DEBUG_COMMANDS,
  BROWSER_TARGET_LABELS,
  defaultTarget,
  type BrowserTarget,
} from "../../lib/browserCommand";

/** Green/red connection dot with a text label — colour is never the only signal. */
export function ConnectionStatus({ connected }: { connected: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-sm font-medium ${connected ? "text-success" : "text-danger"}`}
    >
      <span
        aria-hidden
        className={`size-2.5 rounded-full ${connected ? "bg-success" : "bg-danger"}`}
      />
      {connected ? "Connected" : "Disconnected"}
    </span>
  );
}

/** The remote-debugging command for the selected browser/OS. */
export function BrowserCommand() {
  const [target, setTarget] = useState<BrowserTarget>(() => defaultTarget());
  const { browser, shell, command } = BROWSER_DEBUG_COMMANDS[target];
  return (
    <>
      <div
        role="tablist"
        aria-label="Operating system and browser"
        className="mt-2 flex flex-wrap gap-1"
      >
        {(Object.keys(BROWSER_TARGET_LABELS) as BrowserTarget[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={target === key}
            className={`rounded-md px-2 py-0.5 text-xs ${target === key ? "bg-accent-soft font-medium" : "text-ink-muted"}`}
            onClick={() => setTarget(key)}
          >
            {BROWSER_TARGET_LABELS[key]}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        For browser-assisted Fill, run this in {shell} to start {browser} with remote debugging on
        port 9222, then check the connection. Keep the browser open while reviewing forms, and use
        this {browser} profile only for job-site logins.
      </p>
      <div className="mt-2 flex items-start gap-2">
        <code className="min-w-0 flex-1 rounded-md bg-paper px-3 py-2 font-mono text-xs [overflow-wrap:anywhere]">
          {command}
        </code>
        <CopyButton label="Copy command" text={command} />
      </div>
    </>
  );
}
