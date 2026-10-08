import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { fetchSetupStatus, type SetupStatus } from "../api";
import { onAppEvent } from "../lib/appEvents";
import { setupPillLabel } from "../lib/setupStatus";
import { toneChipClass } from "../lib/tone";
import { StatusMark } from "./ui/Status";

/**
 * Header pill + checklist of prerequisites (model reachable, template, resume, profile).
 * Refreshes on navigation, when the tab regains focus, every minute, and when another
 * page reports a change that affects it (`rt:setup-changed`, e.g. a successful model test).
 */
export function SetupHealth() {
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

  if (!status) return null;
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className={`rt-header-pill rt-control inline-flex items-center justify-center gap-[7px] whitespace-nowrap rounded-sm px-3 py-1 ${toneChipClass(status.ready ? "done" : "attention")}`}
      >
        <StatusMark tone={status.ready ? "done" : "attention"} />
        {setupPillLabel(status)}
      </button>
      {open && (
        <div
          id={panelId}
          className="absolute left-0 top-full z-40 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-sm sm:left-auto sm:right-0 bg-chrome p-4 shadow-lg"
        >
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
                      onClick={() => setOpen(false)}
                      className="mt-1 inline-block text-xs font-semibold text-accent underline-offset-2 hover:underline"
                    >
                      {item.fix.label}
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {!status.ready && (
            <Link
              to="/welcome"
              onClick={() => setOpen(false)}
              className="mt-4 block rounded-sm border border-line-hover px-3 py-2 text-center text-[13px] font-medium text-ink hover:border-ink"
            >
              Open guided setup
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
