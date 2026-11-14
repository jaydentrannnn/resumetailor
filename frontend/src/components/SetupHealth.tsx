import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { fetchSetupStatus, type SetupStatus } from "../api";
import { onAppEvent } from "../lib/appEvents";
import { guidePillLabel, guideProgress } from "../lib/guide";
import { setupPillLabel } from "../lib/setupStatus";
import { toneChipClass } from "../lib/tone";
import { useGuide } from "../state/guideState";
import { GuideSteps } from "./GettingStarted";
import { StatusMark } from "./ui/Status";

/**
 * Rail pill + checklist of prerequisites (model reachable, template, resume, profile).
 * Refreshes on navigation, when the tab regains focus, every minute, and when another
 * page reports a change that affects it (`rt:setup-changed`, e.g. a successful model test).
 * While the Getting started guide is showing, the pill counts its steps and the panel
 * lists them instead of the checklist.
 */
export function SetupHealth() {
  const guide = useGuide();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();

  const load = useCallback(() => {
    fetchSetupStatus()
      .then(setStatus)
      .catch(() => setStatus(null)); // the pill is advisory; hide it on failure
  }, []);

  useEffect(() => {
    load();
  }, [load, location.pathname]);

  useEffect(() => {
    const offSetup = onAppEvent("rt:setup-changed", load);
    const offTemplate = onAppEvent("rt:template-changed", load);
    return () => {
      offSetup();
      offTemplate();
    };
  }, [load]);

  useEffect(() => {
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

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const steps = guide.active ? guide.steps : null;
  const setupLeft = !!status && !status.ready;
  // Ready needs no reminder: the pill shows only while setup or the guide has steps left.
  if (!setupLeft && !steps) return null;
  const tone = setupLeft ? "attention" : "neutral";
  const counts = steps ? guideProgress(steps) : null;
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={
          counts ? `Getting started: ${counts.done} of ${counts.total} steps done` : undefined
        }
        onClick={() => setOpen((v) => !v)}
        className={`rt-header-pill rt-control inline-flex items-center justify-center gap-[7px] whitespace-nowrap rounded-sm px-3 py-1 ${toneChipClass(tone)}`}
      >
        <StatusMark tone={tone} />
        {steps ? guidePillLabel(steps) : status && setupPillLabel(status)}
      </button>
      {open && (
        <div
          id={panelId}
          className="absolute bottom-0 left-full z-40 ml-3 max-h-[calc(100vh-2rem)] w-80 max-w-[calc(100vw-5rem)] overflow-y-auto rounded-sm bg-chrome p-4 shadow-lg"
        >
          {/* One list at a time, so the panel always fits the window: the guide's first
              step already names the setup item still missing and links to its fix. */}
          {steps ? (
            <div>
              <div className="mb-3 flex items-baseline justify-between gap-3">
                <p className="rt-tile-title">Getting started</p>
                <button
                  type="button"
                  className="rt-link text-xs"
                  onClick={() => {
                    setOpen(false);
                    void guide.hide();
                  }}
                >
                  Hide guide
                </button>
              </div>
              <GuideSteps steps={steps} onNavigate={() => setOpen(false)} />
            </div>
          ) : (
            setupLeft && <SetupChecklist status={status} onNavigate={() => setOpen(false)} />
          )}
        </div>
      )}
    </div>
  );
}

/** The prerequisites list: what is in place, what is missing and where to fix it. */
function SetupChecklist({ status, onNavigate }: { status: SetupStatus; onNavigate: () => void }) {
  return (
    <>
      <p className="rt-tile-title mb-3">Setup checklist</p>
      <ul className="space-y-3">
        {status.items.map((item) => (
          <li key={item.id} className="flex gap-3 text-sm">
            <span
              aria-hidden="true"
              className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-sm ${toneChipClass(
                item.ok ? "done" : item.optional ? "muted" : "attention",
              )}`}
            >
              <StatusMark tone={item.ok ? "done" : item.optional ? "muted" : "attention"} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-ink">
                {item.label}
                <span className="sr-only">
                  {item.ok ? " (done)" : item.optional ? " (optional)" : " (needed)"}
                </span>
                {item.optional && !item.ok && (
                  <span className="ml-1 text-xs font-normal text-ink-muted">optional</span>
                )}
              </p>
              <p className="text-xs text-ink-muted">{item.detail}</p>
              {!item.ok && (
                <Link
                  to={item.fix.to}
                  onClick={onNavigate}
                  className="rt-link mt-1 inline-block text-xs font-semibold"
                >
                  {item.fix.label}
                </Link>
              )}
            </div>
          </li>
        ))}
      </ul>
      <Link
        to="/welcome"
        onClick={onNavigate}
        className="mt-4 block rounded-sm border border-line-hover px-3 py-2 text-center text-[13px] font-medium text-ink hover:border-ink"
      >
        Open guided setup
      </Link>
    </>
  );
}
