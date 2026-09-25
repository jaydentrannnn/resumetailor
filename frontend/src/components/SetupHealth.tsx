import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { fetchSetupStatus, type SetupStatus } from "../api";
import { setupPillLabel } from "../lib/setupStatus";

/**
 * Header pill + checklist of prerequisites (model reachable, template, resume, profile).
 * Refreshes on navigation, when the tab regains focus, and every minute.
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
        className={`rounded-full border px-3 py-1 text-xs font-semibold ${
          status.ready
            ? "border-success/40 bg-success-soft text-success"
            : "border-warn/40 bg-warn-soft text-warn"
        }`}
      >
        <span aria-hidden="true">{status.ready ? "● " : "◐ "}</span>
        {setupPillLabel(status)}
      </button>
      {open && (
        <div
          id={panelId}
          className="absolute left-0 top-full z-40 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl sm:left-auto sm:right-0 border border-line bg-panel p-4 shadow-lg"
        >
          <p className="mb-3 text-sm font-semibold text-ink">Setup checklist</p>
          <ul className="space-y-3">
            {status.items.map((item) => (
              <li key={item.id} className="flex gap-3 text-sm">
                <span
                  aria-hidden="true"
                  className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    item.ok
                      ? "bg-success-soft text-success"
                      : item.optional
                        ? "bg-paper text-ink-muted"
                        : "bg-warn-soft text-warn"
                  }`}
                >
                  {item.ok ? "✓" : item.optional ? "–" : "!"}
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
              className="mt-4 block rounded-md border border-line px-3 py-2 text-center text-sm font-semibold text-accent hover:bg-accent-soft"
            >
              Open guided setup
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
