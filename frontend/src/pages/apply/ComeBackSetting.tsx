import { Switch } from "../../components/ui";

/**
 * Whether a fill that stops on questions moves to the back of the batch and comes back
 * by itself (once they're answered in the tab, or after the wait), and how long it waits.
 * Off: it stays in Needs you for Continue fill, as before.
 */
export function ComeBackSetting({
  on,
  minutes,
  onChange,
}: {
  on: boolean;
  minutes: number;
  onChange: (patch: { come_back_stuck?: boolean; come_back_after_min?: number }) => void;
}) {
  return (
    <div className="mt-3">
      <label className="flex items-center gap-2.5 font-medium">
        <Switch checked={on} onChange={(next) => onChange({ come_back_stuck: next })} />
        Come back to stuck applications
      </label>
      <label className="mt-2 block" aria-disabled={!on}>
        Wait up to{" "}
        <input
          className="field mx-1 inline-block w-16"
          type="number"
          min={1}
          max={30}
          disabled={!on}
          aria-label="Minutes before coming back"
          value={minutes}
          onChange={(e) =>
            onChange({
              come_back_after_min: Math.min(30, Math.max(1, Number(e.target.value) || 1)),
            })
          }
        />{" "}
        minutes
      </label>
      <p className="mt-1 text-xs text-ink-muted">
        A fill that needs your answers moves to the back of the queue and continues once you&apos;ve
        answered, or after {minutes} minute{minutes === 1 ? "" : "s"}. It comes back twice at most,
        then waits in Needs you.
      </p>
    </div>
  );
}
