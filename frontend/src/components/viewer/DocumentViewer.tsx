import { type ReactNode, useEffect, useState } from "react";
import { usePrintTarget } from "../../lib/printTarget";
import { stepZoom, type ViewerFit, viewerSrc } from "../../lib/viewer";
import { OpenDocumentLink } from "../FileActions";
import { SEGMENT_BASE, SEGMENT_OFF, SEGMENT_ON, SEGMENT_TRACK } from "../ui/Segmented";

export type ViewerDoc = {
  id: string;
  label: string;
  /** Null when there is no PDF to show; `empty` explains why. */
  src: string | null;
  empty?: ReactNode;
  /** Save as…, Show in folder and the like, for this document. */
  actions?: ReactNode;
};

/**
 * The one PDF viewer (Tailor, an application, Template): a toolbar with the document
 * tabs, Fit width / Fit page and zoom, Open in window and the document's own actions,
 * over a single embedded PDF. Ctrl+P prints the document shown. Only one PDF frame
 * mounts at a time: Chromium on Windows shares one PDF plugin, and two embeds often
 * leave one blank.
 */
export function DocumentViewer({
  docs,
  label,
  active,
  onActive,
  frameKey = "",
  className = "h-[70vh]",
}: {
  docs: ViewerDoc[];
  /** Accessible name of the viewer and its frame. */
  label: string;
  active?: string;
  onActive?: (id: string) => void;
  /** Changes when the shown file was re-rendered, so the frame reloads. */
  frameKey?: string;
  /** Height of the document area. */
  className?: string;
}) {
  const [own, setOwn] = useState(docs[0]?.id ?? "");
  const shown = docs.find((doc) => doc.id === (active ?? own)) ?? docs[0];
  const [fit, setFit] = useState<ViewerFit>("width");
  usePrintTarget(shown?.src ?? null);
  useEffect(() => setFit("width"), [shown?.src]);
  const choose = (id: string) => (onActive ? onActive(id) : setOwn(id));
  if (!shown) return null;

  return (
    <section aria-label={label} className="overflow-hidden rounded-sm border border-line">
      <div
        role="toolbar"
        aria-label={`${label} toolbar`}
        className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 border-b border-line bg-chrome px-3 py-1.5 text-xs"
      >
        {docs.length > 1 && (
          <div role="group" aria-label="Document" className={SEGMENT_TRACK}>
            {docs.map((doc) => (
              <button
                key={doc.id}
                type="button"
                aria-pressed={doc.id === shown.id}
                onClick={() => choose(doc.id)}
                className={`${SEGMENT_BASE} ${doc.id === shown.id ? SEGMENT_ON : SEGMENT_OFF}`}
              >
                {doc.label}
              </button>
            ))}
          </div>
        )}
        {shown.src && <FitControls fit={fit} onFit={setFit} />}
        <div className="flex-1" />
        {shown.src && <OpenDocumentLink href={shown.src} className="rt-link text-xs" />}
        {shown.actions}
      </div>
      <div className="bg-sunken">
        {shown.src ? (
          <iframe
            key={`${shown.src}|${fit}|${frameKey}`}
            title={`${shown.label} preview`}
            src={viewerSrc(shown.src, fit)}
            className={`block w-full bg-doc-preview ${className}`}
          >
            <p className="p-4 text-sm text-ink-muted">
              PDF preview is not available here. <OpenDocumentLink href={shown.src} />.
            </p>
          </iframe>
        ) : (
          <div className="p-6 text-sm text-ink-muted">{shown.empty}</div>
        )}
      </div>
    </section>
  );
}

function FitControls({ fit, onFit }: { fit: ViewerFit; onFit: (fit: ViewerFit) => void }) {
  return (
    <>
      <div role="group" aria-label="Fit" className={SEGMENT_TRACK}>
        {(["width", "page"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={fit === mode}
            onClick={() => onFit(mode)}
            className={`${SEGMENT_BASE} ${fit === mode ? SEGMENT_ON : SEGMENT_OFF}`}
          >
            {mode === "width" ? "Fit width" : "Fit page"}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-0.5">
        <ZoomButton label="Zoom out" onClick={() => onFit(stepZoom(fit, -1))}>
          −
        </ZoomButton>
        <span className="min-w-10 text-center font-mono tabular-nums text-ink-2">
          {typeof fit === "number" ? `${fit}%` : "Fit"}
        </span>
        <ZoomButton label="Zoom in" onClick={() => onFit(stepZoom(fit, 1))}>
          +
        </ZoomButton>
      </div>
    </>
  );
}

function ZoomButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="rt-row-action size-7 rounded-sm text-[15px] text-ink hover:bg-sunken"
    >
      {children}
    </button>
  );
}
