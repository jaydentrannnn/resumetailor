import { useCallback, useEffect, useState } from "react";
import { fetchAutomation, setAutomationPaused, type AutomationState } from "../api";
import { describe } from "../lib/errors";
import { useToast } from "../lib/toast";

/**
 * Header "Pause all automation" switch (plan P4-S). While paused, batches wait before
 * their next application, the nightly run does not start and nothing is auto-submitted.
 * Refreshes when the tab regains focus and every minute, like the setup pill.
 */
export function AutomationSwitch() {
  const [state, setState] = useState<AutomationState | null>(null);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  const load = useCallback(() => {
    fetchAutomation()
      .then(setState)
      .catch(() => setState(null));
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 60_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  if (!state) return null;

  const toggle = async () => {
    setSaving(true);
    try {
      const next = await setAutomationPaused(!state.paused);
      setState(next);
      toast.success(next.paused ? "Automation paused" : "Automation resumed");
    } catch (err) {
      toast.error("Could not change automation", describe(err).detail);
    } finally {
      setSaving(false);
    }
  };

  const usage = `${state.auto_submits_24h} of ${state.max_per_day} automatic submits in the last 24 hours`;
  return (
    <button
      type="button"
      aria-pressed={state.paused}
      disabled={saving}
      onClick={toggle}
      title={state.paused ? `Automation is paused. ${usage}.` : `Pause all automation. ${usage}.`}
      className={`rt-header-pill rt-control inline-flex items-center justify-center gap-1 whitespace-nowrap rounded-full border px-3 py-1 ${
        state.paused
          ? "border-warn/40 bg-warn-soft text-warn"
          : "border-line bg-panel text-ink-muted hover:text-ink"
      }`}
    >
      <span aria-hidden="true">{state.paused ? "▶ " : "❚❚ "}</span>
      {state.paused ? "Automation paused · Resume" : "Pause automation"}
    </button>
  );
}
