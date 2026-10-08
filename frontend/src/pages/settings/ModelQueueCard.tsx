import { useEffect, useState } from "react";
import { fetchModelQueue, saveModelQueue, type ModelQueueStatus } from "../../api";
import { Button, Card } from "../../components/ui";
import { startAdaptivePoll } from "../../lib/adaptivePoll";
import { useToast } from "../../lib/toast";

export function ModelQueueCard() {
  const [status, setStatus] = useState<ModelQueueStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  useEffect(() => {
    let live = true;
    const poll = startAdaptivePoll(async () => {
      try {
        const next = await fetchModelQueue();
        if (live) {
          setStatus(next);
          setError(null);
        }
        return next.endpoints.some((e) => e.active || e.waiting);
      } catch (err) {
        if (live) setError(String(err));
        return false;
      }
    });
    return () => {
      live = false;
      poll.stop();
    };
  }, []);

  async function update(key: string, value: number) {
    if (!status) return;
    setBusy(true);
    try {
      const settings = { ...status.settings };
      if (key === "local_concurrency" || key === "cloud_concurrency") settings[key] = value;
      else settings.endpoint_limits = { ...settings.endpoint_limits, [key]: value };
      setStatus(await saveModelQueue(settings));
    } catch (err) {
      toast.error("Couldn't save model request limits", String(err));
    } finally {
      setBusy(false);
    }
  }

  const limit = (label: string, key: string, value: number) => (
    <label className="grid min-w-0 gap-3 text-sm sm:grid-cols-[minmax(0,1fr)_80px] sm:items-center">
      <span className="break-words font-medium">{label}</span>
      <select
        className="field w-20"
        aria-label={label}
        value={value}
        disabled={busy}
        onChange={(e) => void update(key, Number(e.target.value))}
      >
        {Array.from({ length: 16 }, (_, i) => i + 1).map((n) => (
          <option key={n}>{n}</option>
        ))}
      </select>
    </label>
  );
  return (
    <Card
      title="Simultaneous model requests"
      description="Shared by Tailor, Apply, and all profiles. Requests wait for capacity; the next starts as soon as a slot opens."
    >
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      {status ? (
        <div className="space-y-3">
          {limit("Local server limit", "local_concurrency", status.settings.local_concurrency)}
          {limit("Cloud endpoint limit", "cloud_concurrency", status.settings.cloud_concurrency)}
          {status.endpoints.map((e) => (
            <div key={e.endpoint} className="border-t border-line pt-4">
              {limit(e.endpoint, e.endpoint, e.limit)}
              <p className="mt-1 text-xs text-ink-muted">
                {e.active} active · {e.waiting} waiting
                {e.cooldown_seconds > 0 ? ` · Rate limit: waiting ${e.cooldown_seconds}s` : ""}
              </p>
            </div>
          ))}
          {Object.keys(status.settings.endpoint_limits).length > 0 && (
            <Button
              size="sm"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  setStatus(await saveModelQueue({ ...status.settings, endpoint_limits: {} }));
                } catch (err) {
                  toast.error("Couldn't reset endpoint limits", String(err));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Use default endpoint limits
            </Button>
          )}
        </div>
      ) : (
        !error && <p className="text-sm text-ink-muted">Loading request limits…</p>
      )}
    </Card>
  );
}
