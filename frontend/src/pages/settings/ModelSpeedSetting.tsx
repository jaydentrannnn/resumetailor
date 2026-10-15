import { useEffect, useState } from "react";
import { fetchModelQueue, saveModelQueue, type ModelQueueStatus } from "../../api";
import { Button } from "../../components/ui";
import { startAdaptivePoll } from "../../lib/adaptivePoll";
import {
  presetFor,
  withSpeedPreset,
  SPEED_PRESETS,
  type SpeedPresetId,
} from "../../lib/speedPresets";
import { useToast } from "../../lib/toast";
import { queueEndpoints } from "../../lib/modelEndpoints";
import { useRunState } from "../../state/runState";
import { SELECT_WIDTH } from "./selectWidth";
import { SettingRow } from "./SettingRow";

/**
 * How many model requests run at once, as a speed-vs-rate-limits choice. Shared by
 * Tailor, Apply and every profile. "Custom" reveals the raw limits per server.
 */
export function ModelSpeedSetting() {
  const [status, setStatus] = useState<ModelQueueStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const { settings: appSettings, config } = useRunState();
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
  const preset: SpeedPresetId = presetFor(status.settings);
  const help = SPEED_PRESETS.find((p) => p.id === preset)?.help;
  const endpoints = queueEndpoints(appSettings, config, status);

  function setLimit(key: string, value: number) {
    const settings = { ...status!.settings };
    if (key === "local_concurrency" || key === "cloud_concurrency") settings[key] = value;
    else settings.endpoint_limits = { ...settings.endpoint_limits, [key]: value };
    void save(settings);
  }
  const limit = (label: string, key: string, value: number, note?: string) => (
    <label
      key={key}
      className="grid min-w-0 gap-2 text-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-6"
    >
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
    <>
      <SettingRow
        label="Request concurrency"
        layout="split"
        description={
          help ??
          "Maximum simultaneous requests to each server. Extra requests wait for a free slot."
        }
      >
        <select
          className={`field ${SELECT_WIDTH}`}
          aria-label="Request concurrency"
          value={preset}
          disabled={busy}
          onChange={(e) => {
            const id = e.target.value as SpeedPresetId;
            void save(withSpeedPreset(status.settings, id));
          }}
        >
          {SPEED_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
          <option value="custom">Custom</option>
        </select>
      </SettingRow>
      {preset === "custom" && (
        <div className="space-y-3 pb-4">
          {limit("Local requests at once", "local_concurrency", status.settings.local_concurrency)}
          {limit("Cloud requests at once", "cloud_concurrency", status.settings.cloud_concurrency)}
          <details className="border-t border-line pt-3">
            <summary className="cursor-pointer text-sm font-medium">Per-server overrides</summary>
            <div className="mt-3 space-y-3">
              {endpoints.map(({ endpoint, label, inherited, live }) => (
                <div
                  key={endpoint}
                  className="min-w-0 border-t border-line pt-3 first:border-0 first:pt-0"
                >
                  <label className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-6">
                    <span className="min-w-0 text-sm" title={endpoint}>
                      {label}
                      <span className="block truncate text-xs text-ink-muted">{endpoint}</span>
                    </span>
                    <select
                      className={`field ${SELECT_WIDTH}`}
                      aria-label={`${label} limit`}
                      disabled={busy}
                      value={status.settings.endpoint_limits[endpoint] ?? ""}
                      onChange={(e) => {
                        const limits = { ...status.settings.endpoint_limits };
                        if (e.target.value) limits[endpoint] = Number(e.target.value);
                        else delete limits[endpoint];
                        void save({ ...status.settings, endpoint_limits: limits });
                      }}
                    >
                      <option value="">Use default ({inherited})</option>
                      {Array.from({ length: 16 }, (_, i) => i + 1).map((n) => (
                        <option key={n}>{n}</option>
                      ))}
                    </select>
                  </label>
                  {live && (live.active > 0 || live.waiting > 0 || live.cooldown_seconds > 0) && (
                    <p className="mt-1 text-xs text-ink-muted" role="status">
                      {live.active} running · {live.waiting} waiting
                      {live.cooldown_seconds > 0 ? ` · retrying in ${live.cooldown_seconds}s` : ""}
                    </p>
                  )}
                </div>
              ))}
              {!endpoints.length && (
                <p className="text-xs text-ink-muted">
                  Choose a model to configure its server limit.
                </p>
              )}
            </div>
          </details>
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
    </>
  );
}
