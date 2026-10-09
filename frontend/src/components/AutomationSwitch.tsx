import { useCallback, useEffect, useState } from "react";
import { fetchAutomation, setAutomationPaused, type AutomationState } from "../api";
import { describe } from "../lib/errors";
import { useToast } from "../lib/toast";
import { toneChipClass } from "../lib/tone";
import { StatusMark } from "./ui/Status";

/**
 * Header "Pause all automation" switch (plan P4-S). While paused, batches wait before
 * their next application, the nightly run does not start and nothing is auto-submitted.
 * Refreshes when the tab regains focus and every minute, like the setup pill. Running, it
 * is plain text like the nav; paused, it becomes an attention chip so the state stands out.
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
      className={`rt-header-pill rt-control inline-flex items-center justify-center gap-[7px] whitespace-nowrap rounded-sm px-3 py-1 ${
        state.paused
          ? toneChipClass("attention")
          : "text-ink-muted hover:text-ink"
      }`}
    >
      {state.paused ? <StatusMark tone="attention" /> : <PauseIcon />}
      {state.paused ? "Automation paused · Resume" : "Pause automation"}
    </button>
  );
}

/** Two bars, drawn in the text colour so the running state needs no box. */
function PauseIcon() {
  return (
    <svg aria-hidden viewBox="0 0 12 12" className="size-3 shrink-0" fill="currentColor">
      <rect x="2.5" y="2" width="2.25" height="8" />
      <rect x="7.25" y="2" width="2.25" height="8" />
    </svg>
  );
}
