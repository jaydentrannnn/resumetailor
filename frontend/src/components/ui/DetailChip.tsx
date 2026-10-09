import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Tone } from "../../lib/tone";
import { StatusChip } from "./Status";

const WIDTH = 320;
const GAP = 6;

/**
 * A status chip that carries a longer explanation (a failed row's error) instead of a
 * squeezed line beside it. Hover or keyboard focus shows the text; a tap toggles it for
 * touch. Portaled and fixed so a table's scroll container cannot clip it.
 */
export function DetailChip({
  tone,
  children,
  detail,
  label,
}: {
  tone: Tone;
  children: ReactNode;
  detail: string;
  /** The tooltip's heading, e.g. "Why it failed". */
  label: string;
}) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [at, setAt] = useState<{ left: number; top?: number; bottom?: number } | null>(null);
  const id = useId();

  function show() {
    const rect = anchor.current?.getBoundingClientRect();
    if (!rect) return;
    const viewW = document.documentElement.clientWidth || window.innerWidth;
    const below = rect.bottom + GAP + 160 <= window.innerHeight;
    setAt({
      left: Math.max(8, Math.min(rect.left, viewW - Math.min(WIDTH, viewW - 16) - 8)),
      top: below ? rect.bottom + GAP : undefined,
      bottom: below ? undefined : window.innerHeight - rect.top + GAP,
    });
  }
  const hide = () => setAt(null);

  useEffect(() => {
    if (!at) return;
    const key = (event: KeyboardEvent) => event.key === "Escape" && hide();
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [at]);

  return (
    <>
      <button
        ref={anchor}
        type="button"
        aria-describedby={at ? id : undefined}
        aria-label={`${typeof children === "string" ? children : label}: ${detail}`}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={() => (at ? hide() : show())}
        className="inline-flex cursor-help rounded-sm"
      >
        <StatusChip
          tone={tone}
          className="underline decoration-dotted decoration-1 underline-offset-[3px]"
        >
          {children}
        </StatusChip>
      </button>
      {at &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            className="fixed z-50 max-h-[60vh] overflow-auto rounded-sm border border-line bg-chrome px-3 py-2.5 text-[13px] leading-relaxed text-ink shadow-lg"
            style={{ width: Math.min(WIDTH, window.innerWidth - 16), ...at }}
          >
            <p className="rt-eyebrow mb-1">{label}</p>
            <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{detail}</p>
          </div>,
          document.body,
        )}
    </>
  );
}
