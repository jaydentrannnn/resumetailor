import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

/** Open dialogs, newest last: only the topmost handles Escape and Tab (a confirm over a drawer). */
const openDialogs: object[] = [];

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

/**
 * Accessible modal dialog with focus trap, Escape-to-close, and focus restore.
 *
 * Backdrop closes only when both mousedown and click land on the overlay itself —
 * a text selection dragged outside the panel and released must not dismiss the dialog
 * (that used to discard a half-typed profile label).
 *
 * Portalled to `document.body` so dialogs stack in the order they open: a confirm
 * raised from inside another dialog (delete a profile) lands on top of it, whatever
 * each one's place in the React tree.
 */
export function Modal({
  title,
  onClose,
  children,
  wide,
  placement = "center",
  size = "md",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Wider panel for pack editors and similar dense content. */
  wide?: boolean;
  /** "right" renders a full-height side drawer (Apply settings). */
  placement?: "center" | "right";
  /** Width of a right-hand drawer; centered dialogs keep using `wide`. */
  size?: "md" | "lg";
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const overlayMouseDown = useRef(false);
  // Read through a ref so a parent re-render (a new inline `onClose`) never re-runs the
  // focus effect below, which would pull focus out of a field mid-typing.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    /** Standard modal keyboard contract: focus moves in on open and back to the
     * trigger on close, Escape closes, and Tab cannot leave the dialog. */
    const previouslyFocused = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    const token = {};
    openDialogs.push(token);

    function onKeyDown(e: KeyboardEvent) {
      if (openDialogs[openDialogs.length - 1] !== token) return;
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusables = dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      openDialogs.splice(openDialogs.indexOf(token), 1);
      previouslyFocused?.focus();
    };
  }, []);

  return createPortal(
    <div
      // `overflow-y-auto` here (not on the panel) so content taller than the viewport
      // scrolls the whole dialog, header included — a wide modal over dense content
      // (a long form or list) can easily exceed viewport height.
      className={
        placement === "right"
          ? "fixed inset-0 z-50 flex justify-end bg-scrim"
          : "fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-scrim px-4 py-12"
      }
      onMouseDown={(e) => {
        overlayMouseDown.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (overlayMouseDown.current && e.target === e.currentTarget) onClose();
        overlayMouseDown.current = false;
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={
          placement === "right"
            ? `h-full w-full overflow-y-auto bg-chrome p-5 shadow-lg outline-none ${size === "lg" ? "max-w-2xl" : "max-w-md"}`
            : `w-full rounded-sm bg-chrome p-5 shadow-lg outline-none sm:px-6 sm:py-[22px] ${
                wide ? "max-w-2xl" : "max-w-lg"
              }`
        }
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3">
          <h2 id={titleId} className="text-base font-semibold">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-sm px-2 py-1 text-sm text-ink-muted hover:text-ink"
          >
            Close
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
