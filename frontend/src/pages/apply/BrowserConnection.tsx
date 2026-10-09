import type { BrowserId, BrowserStatus } from "../../api";
import { Button, Segmented, StatusChip } from "../../components/ui";
import { BROWSERS, CHIP_LABEL, type BrowserView } from "../../lib/browserState";

const CHIP_TONE = { ready: "done", idle: "neutral", unavailable: "attention" } as const;

/** The browser's state as a status chip; the reason, when there is one, as its tooltip. */
export function ConnectionStatus({ view }: { view: BrowserView }) {
  return (
    <span title={view.reason || undefined}>
      <StatusChip tone={CHIP_TONE[view.state]}>{CHIP_LABEL[view.state]}</StatusChip>
    </span>
  );
}

/**
 * Which browser the app starts for Fill and job fetches. Browsers not installed here are
 * greyed out. In Docker the app can't start a host program, so only the manual flag shows.
 */
export function BrowserPicker({
  status,
  view,
  selected,
  onSelect,
  launch,
}: {
  status: BrowserStatus | null;
  view: BrowserView;
  selected: BrowserId | null;
  onSelect: (id: BrowserId) => void;
  launch: { run: () => void; busy: boolean };
}) {
  if (status?.docker)
    return (
      <p className="text-xs text-ink-muted">
        Start a Chromium browser on the host with{" "}
        <code className="font-mono">--remote-debugging-port=9222</code> and a separate{" "}
        <code className="font-mono">--user-data-dir</code>.
      </p>
    );
  const installed = status?.installed ?? {};
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          label="Browser for Fill"
          items={BROWSERS.map(({ id, label }) => ({
            id,
            label: installed[id] || !status ? label : `${label} · not installed`,
            disabled: !!status && !installed[id],
          }))}
          value={selected ?? view.resolved ?? ""}
          onChange={(id) => onSelect(id as BrowserId)}
        />
        <Button
          variant="plain"
          size="sm"
          disabled={launch.busy || view.state !== "idle"}
          onClick={launch.run}
        >
          {launch.busy ? "Starting…" : "Launch now"}
        </Button>
      </div>
      {view.state === "unavailable" && view.reason && (
        <p className="mt-2 text-xs text-ink-muted">{view.reason}</p>
      )}
      <p className="mt-2 text-xs text-ink-muted">
        It opens by itself when Fill or a job fetch needs it, in its own ResumeTailor profile beside
        your everyday windows. Sign in to job sites there, and use it only for them.
      </p>
    </>
  );
}
