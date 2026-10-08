import { type ReactNode, useEffect, useId, useRef, useState } from "react";

/**
 * A "?" button that opens a short plain-language explanation. Opens on click (touch
 * friendly), closes on Escape, outside click, or a second click.
 */
export function InlineHelp({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);
  return (
    <span ref={ref} className="relative inline-flex align-middle">
      <button
        type="button"
        aria-label={`What is ${label}?`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="rt-row-action inline-flex size-5 min-h-0 items-center justify-center rounded-sm border border-line-hover text-micro font-semibold text-ink-muted hover:border-ink hover:text-ink"
      >
        ?
      </button>
      {open && (
        <span
          id={id}
          role="note"
          className="absolute left-1/2 top-full z-40 mt-2 w-64 -translate-x-1/2 rounded-sm bg-chrome p-3 text-left text-xs font-normal leading-relaxed text-ink shadow-lg"
        >
          {children}
        </span>
      )}
    </span>
  );
}
