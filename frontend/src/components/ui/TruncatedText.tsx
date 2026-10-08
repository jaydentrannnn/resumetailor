import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const WIDTH = 448; // 28rem
const GAP = 6;

/**
 * One line of text that never wraps. When the line is actually cut off it becomes a button;
 * clicking it opens a floating box with the full text right where the click landed (keyboard
 * activation anchors to the line itself). Outside click, Escape, scroll, resize or Close
 * dismiss it, and Escape/Close return focus to the line. Colour comes from `className`.
 */
export function TruncatedText({
  text,
  className = "",
  label = "Show full text",
}: {
  text: string;
  className?: string;
  label?: string;
}) {
  const line = useRef<HTMLElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [cut, setCut] = useState(false);
  const [at, setAt] = useState<{ x: number; y: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const el = line.current;
    if (!el) return;
    const measure = () => setCut(el.scrollWidth > el.clientWidth + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, cut]);

  useEffect(() => {
    if (!at) return;
    const dismiss = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!box.current?.contains(target) && !line.current?.contains(target)) setAt(null);
    };
    const close = () => setAt(null);
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setAt(null);
      line.current?.focus();
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [at]);

  const base = `block min-w-0 max-w-full truncate text-left ${className}`.trim();
  if (!cut)
    return (
      <span ref={line} className={base}>
        {text}
      </span>
    );

  function toggle(event: React.MouseEvent<HTMLButtonElement>) {
    if (at) return setAt(null);
    const rect = event.currentTarget.getBoundingClientRect();
    const fromPointer = event.clientX !== 0 || event.clientY !== 0;
    setAt({
      x: fromPointer ? event.clientX : rect.left,
      y: fromPointer ? event.clientY : rect.bottom,
      top: rect.top,
    });
  }

  // clientWidth excludes the page scrollbar, so the box never slides underneath it.
  const viewW = document.documentElement.clientWidth || window.innerWidth;
  const below = at ? at.y + GAP + 200 <= window.innerHeight : true;
  return (
    <>
      <button
        ref={line as React.RefObject<HTMLButtonElement>}
        type="button"
        aria-expanded={!!at}
        aria-label={`${label}: ${text}`}
        onClick={toggle}
        className={`${base} cursor-pointer underline decoration-dotted decoration-1 underline-offset-2 hover:decoration-solid`}
      >
        {text}
      </button>
      {at &&
        createPortal(
          <div
            ref={box}
            role="dialog"
            aria-label={label}
            className="fixed z-50 max-h-[60vh] overflow-auto rounded-sm bg-chrome p-3 text-[13px] leading-relaxed text-ink shadow-xl"
            style={{
              width: Math.min(WIDTH, viewW - 16),
              left: Math.max(8, Math.min(at.x - 16, viewW - Math.min(WIDTH, viewW - 16) - 8)),
              top: below ? at.y + GAP : undefined,
              bottom: below ? undefined : window.innerHeight - Math.min(at.y, at.top) + GAP,
            }}
          >
            <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{text}</p>
            <div className="mt-2 flex justify-end">
              <button
                type="button"
                className="rt-row-action rounded-sm px-2 text-xs font-medium text-ink-muted hover:bg-sunken hover:text-ink"
                onClick={() => {
                  setAt(null);
                  line.current?.focus();
                }}
              >
                Close
              </button>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
