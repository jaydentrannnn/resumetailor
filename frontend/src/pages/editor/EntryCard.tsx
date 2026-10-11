import { useId, type ReactNode } from "react";
import type { Section } from "../../lib/resumeEdit";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";
import { EntryActions } from "./EntryActions";
import { useEntryEditor } from "./EntryEditorContext";

export function EntryCard({
  section,
  index,
  title,
  onMove,
  onRemove,
  children,
}: {
  section: Section;
  index: number;
  title: string;
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
  children: ReactNode;
}) {
  const { expanded, setExpanded } = useEntryEditor();
  const key = resumeEntryKey(section.entries[index]);
  const open = expanded.has(key);
  const bodyId = useId();
  const entry = section.entries[index];
  const dates =
    "dates" in entry
      ? entry.dates
      : "start" in entry
        ? [entry.start, entry.end].filter(Boolean).join(" – ") ||
          ("date" in entry ? entry.date : "")
        : "date" in entry
          ? entry.date
          : "";
  const detail =
    "bullets" in entry
      ? `${entry.bullets.length} bullets`
      : "items" in entry
        ? `${entry.items.length} skills`
        : "degree" in entry
          ? entry.degree
          : "";

  return (
    <div data-resume-entry data-entry-key={key} className="border-t border-line py-4 last:pb-0">
      <div data-entry-summary className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-48">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            aria-label={`${open ? "Collapse" : "Expand"} ${title}`}
            onClick={() => setExpanded(key, !open)}
            className="rt-control flex min-w-0 flex-1 items-center gap-2 rounded-sm py-1 text-left text-sm font-semibold hover:text-accent focus-visible:outline-accent"
          >
            <span aria-hidden="true" className="shrink-0">
              {open ? "▾" : "▸"}
            </span>
            <span className="break-words">{title}</span>
          </button>
          {(dates || detail) && (
            <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-muted">
              {dates && <span className="font-mono">{dates}</span>}
              {detail && <span>{detail}</span>}
            </p>
          )}
        </div>
        <EntryActions
          section={section}
          index={index}
          title={title}
          onMove={onMove}
          onRemove={onRemove}
        />
      </div>
      <div id={bodyId} hidden={!open} className="mt-3">
        {children}
      </div>
    </div>
  );
}
