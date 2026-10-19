import { type ReactNode, useState } from "react";
import { usePrintTarget } from "../../lib/printTarget";
import { viewerSrc } from "../../lib/viewer";
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
 * tabs, Open in window and the document's own actions, over a single embedded PDF
 * framed to the page width (the panes beside it are sized so a page fits). Ctrl+P
 * prints the document shown. Only one PDF frame mounts at a time: Chromium on Windows
 * shares one PDF plugin, and two embeds often leave one blank.
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
  usePrintTarget(shown?.src ?? null);
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
        <div className="flex-1" />
        {shown.src && <OpenDocumentLink href={shown.src} className="rt-link text-xs" />}
        {shown.actions}
      </div>
      <div className="bg-sunken">
        {shown.src ? (
          <iframe
            key={`${shown.src}|${frameKey}`}
            title={`${shown.label} preview`}
            src={viewerSrc(shown.src)}
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
