import { useState } from "react";
import { CopyButton } from "../../components/CopyButton";
import { EDGE_DEBUG_COMMANDS, detectOs, type DesktopOs } from "../../lib/browserCommand";

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

const OS_LABELS: Record<DesktopOs, string> = { windows: "Windows", mac: "macOS", linux: "Linux" };

/** The Edge remote-debugging command for the viewer's OS, with tabs for the others. */
export function BrowserCommand() {
  const [os, setOs] = useState<DesktopOs>(() => detectOs());
  const { shell, command } = EDGE_DEBUG_COMMANDS[os];
  return (
    <>
      <div role="tablist" aria-label="Operating system" className="mt-2 flex gap-1">
        {(Object.keys(OS_LABELS) as DesktopOs[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={os === key}
            className={`rounded-md px-2 py-0.5 text-xs ${os === key ? "bg-accent-soft font-medium" : "text-ink-muted"}`}
            onClick={() => setOs(key)}
          >
            {OS_LABELS[key]}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        For browser-assisted Fill, run this in {shell} to start Edge with remote debugging on port
        9222, then check the connection. Keep the browser open while reviewing forms, and use this
        Edge profile only for job-site logins.
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
