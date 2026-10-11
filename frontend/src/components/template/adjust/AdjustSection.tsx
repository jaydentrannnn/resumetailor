import { useId, type ReactNode } from "react";

/**
 * One collapsible group of Quick adjustments: a header that names it and says what it
 * is set to, and its rows when open. Only one is open at a time (the panel decides), so
 * the column stays short enough to keep the preview in view.
 */
export function AdjustSection({
  title,
  summary,
  open,
  onToggle,
  children,
}: {
  title: string;
  summary: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const bodyId = useId();
  const summaryId = useId();
  return (
    <section className="border-t border-line last:border-b">
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={title}
          aria-describedby={summaryId}
          onClick={onToggle}
          className="flex min-h-11 w-full items-center gap-2 py-2 text-left"
        >
          <span
            aria-hidden
            className={`w-3 shrink-0 text-[10px] leading-none text-ink transition-transform ${open ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          <span className="shrink-0 text-[13px] font-semibold text-ink">{title}</span>
          <span id={summaryId} className="ml-auto min-w-0 truncate pl-3 text-xs text-ink-muted">
            {summary}
          </span>
        </button>
      </h3>
      {open && (
        <div id={bodyId} className="pb-5 pt-1">
          {children}
        </div>
      )}
    </section>
  );
}
