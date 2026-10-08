import { useState, type ReactNode } from "react";
import { buttonClass } from "../../lib/buttonClass";
import { Modal } from "../ui";

/** One horizontally scrolling, snapping row of template cards. */
export function GalleryRow({ children }: { children: ReactNode }) {
  return <ul className="mt-4 flex snap-x snap-mandatory gap-4 overflow-x-auto pb-2">{children}</ul>;
}

/** A 320px card; the selected one gets the selection border. */
export function GalleryCard({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <li
      className={`flex w-[320px] shrink-0 snap-start flex-col overflow-hidden rounded-sm border bg-field text-sm ${
        active ? "border-selected-line" : "border-line"
      }`}
    >
      {children}
    </li>
  );
}

/** The card's action line: never wraps, so every card's buttons sit on one row. */
export function GalleryActions({ children }: { children: ReactNode }) {
  return <div className="mt-auto flex flex-nowrap justify-end gap-2">{children}</div>;
}

/** Class for the "In use" / "Use" button: the selected state reads as a selection, not an action. */
export function selectButtonClass(active: boolean): string {
  return active
    ? buttonClass(
        "secondary",
        "sm",
        "border-selected-line! bg-selected! text-on-selected! disabled:opacity-100",
      )
    : buttonClass("secondary", "sm");
}

/** First page of a template; a plain card when it can't render. */
export function TemplateThumb({ src, alt, label }: { src: string; alt: string; label: string }) {
  const [failed, setFailed] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-label={`Zoom ${label}`}
        disabled={failed}
        onClick={() => setZoomed(true)}
        className="flex aspect-[8.5/5.5] w-full items-start justify-center overflow-hidden bg-doc-preview"
      >
        {failed ? (
          <span className="m-auto px-4 text-center text-xs text-ink-muted">
            Preview unavailable (needs Word or LibreOffice)
          </span>
        ) : (
          <img
            src={src}
            alt={alt}
            loading="lazy"
            className="size-full object-cover object-top"
            onError={() => setFailed(true)}
          />
        )}
      </button>
      {zoomed && (
        <Modal title={label} placement="center" wide onClose={() => setZoomed(false)}>
          <img src={src} alt={alt} className="mt-4 h-auto w-full bg-doc-preview" />
        </Modal>
      )}
    </>
  );
}
