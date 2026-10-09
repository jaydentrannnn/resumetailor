import { useEffect, useState } from "react";
import { fetchModelQueue, saveModelQueue, type ModelQueueStatus } from "../../api";
import { Button } from "../../components/ui";
import { startAdaptivePoll } from "../../lib/adaptivePoll";
import { presetFor, settingsFor, SPEED_PRESETS, type SpeedPresetId } from "../../lib/speedPresets";
import { useToast } from "../../lib/toast";
import { SELECT_WIDTH } from "./selectWidth";
import { SettingRow } from "./SettingRow";

/**
 * How many model requests run at once, as a speed-vs-rate-limits choice. Shared by
 * Tailor, Apply and every profile. "Custom" reveals the raw limits per server.
 */
export function ModelSpeedSetting() {
  const [status, setStatus] = useState<ModelQueueStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [custom, setCustom] = useState(false);
  const toast = useToast();
  useEffect(() => {
    let live = true;
    const poll = startAdaptivePoll(async () => {
      try {
        const next = await fetchModelQueue();
        if (live) setStatus(next);
        return next.endpoints.some((e) => e.active || e.waiting);
      } catch {
        return false;
      }
    });
    return () => {
      live = false;
      poll.stop();
    };
  }, []);

  async function save(settings: ModelQueueStatus["settings"]) {
    setBusy(true);
    try {
      setStatus(await saveModelQueue(settings));
    } catch (err) {
      toast.error("Couldn't save the speed setting", String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;
  const preset: SpeedPresetId = custom ? "custom" : presetFor(status.settings);
  const help = SPEED_PRESETS.find((p) => p.id === preset)?.help;

  function setLimit(key: string, value: number) {
    const settings = { ...status!.settings };
    if (key === "local_concurrency" || key === "cloud_concurrency") settings[key] = value;
    else settings.endpoint_limits = { ...settings.endpoint_limits, [key]: value };
    void save(settings);
  }
  const limit = (label: string, key: string, value: number, note?: string) => (
    <label key={key} className="grid min-w-0 gap-1 text-sm sm:grid-cols-[minmax(0,1fr)_auto]">
      <span className="min-w-0 break-words">
        {label}
        {note && <span className="block text-xs text-ink-muted">{note}</span>}
      </span>
      <select
        className={`field ${SELECT_WIDTH}`}
        aria-label={label}
        value={value}
        disabled={busy}
        onChange={(e) => setLimit(key, Number(e.target.value))}
      >
        {Array.from({ length: 16 }, (_, i) => i + 1).map((n) => (
          <option key={n}>{n}</option>
        ))}
      </select>
    </label>
  );

  return (
    <SettingRow
      label="Speed"
      layout="split"
      description={help ?? "Requests at once, per kind of server. Requests wait for a free slot."}
    >
      <select
        className={`field ${SELECT_WIDTH}`}
        aria-label="Speed"
        value={preset}
        disabled={busy}
        onChange={(e) => {
          const id = e.target.value as SpeedPresetId;
          setCustom(id === "custom");
          if (id !== "custom") void save(settingsFor(id));
        }}
      >
        {SPEED_PRESETS.map((p) => (
          <option key={p.id} value={p.id}>
            {p.label}
          </option>
        ))}
        <option value="custom">Custom</option>
      </select>
      {preset === "custom" && (
        <div className="mt-3 space-y-3">
          {limit("On this computer", "local_concurrency", status.settings.local_concurrency)}
          {limit("Cloud providers", "cloud_concurrency", status.settings.cloud_concurrency)}
          {status.endpoints.map((e) =>
            limit(
              e.endpoint,
              e.endpoint,
              e.limit,
              `${e.active} running · ${e.waiting} waiting${e.cooldown_seconds > 0 ? ` · rate limited, retrying in ${e.cooldown_seconds}s` : ""}`,
            ),
          )}
          {Object.keys(status.settings.endpoint_limits).length > 0 && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void save({ ...status.settings, endpoint_limits: {} })}
            >
              Clear per-server limits
            </Button>
          )}
        </div>
      )}
    </SettingRow>
  );
}
