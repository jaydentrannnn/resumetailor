import { EntryControls } from "../../components/ListControls";
import { useEffect, useRef } from "react";
import { buttonClass } from "../../lib/buttonClass";
import { setEntryDragImage } from "../../lib/entryDragImage";
import { SECTION_KIND_LABELS, type Section } from "../../lib/resumeEdit";
import { isDatedSection } from "../../lib/resumeEntryOrder";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";
import { useEntryEditor } from "./EntryEditorContext";

export function EntryActions({
  section,
  index,
  title,
  onMove,
  onRemove,
}: {
  section: Section;
  index: number;
  title: string;
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
}) {
  const { sections, moveEntry, setDragging } = useEntryEditor();
  const destinations = sections.filter((s) => s.id !== section.id && s.kind === section.kind);
  const key = resumeEntryKey(section.entries[index]);
  const clearDragImage = useRef<(() => void) | null>(null);
  useEffect(() => () => clearDragImage.current?.(), []);
  return (
    <div
      data-entry-actions
      className="ml-auto flex max-w-full shrink-0 flex-wrap items-center justify-end gap-2 sm:flex-nowrap"
    >
      {destinations.length > 0 && (
        <select
          value=""
          aria-label={`Move ${title} to section`}
          onChange={(event) => moveEntry(section.id, key, event.target.value)}
          className="field rt-control w-28 shrink-0 text-xs sm:w-36"
        >
          <option value="" disabled>
            Move to…
          </option>
          {destinations.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title || SECTION_KIND_LABELS[s.kind]}
              {destinations.some((other) => other.id !== s.id && other.title === s.title)
                ? ` (${s.id})`
                : ""}
            </option>
          ))}
        </select>
      )}
      <EntryControls
        index={index}
        total={section.entries.length}
        onMove={onMove}
        onRemove={onRemove}
        canMove={!isDatedSection(section)}
      />
      {destinations.length > 0 && (
        <button
          type="button"
          draggable
          aria-label={`Drag ${title} to another section`}
          title="Drag to another matching section, or use Move to"
          className={buttonClass("ghost", "sm", "cursor-grab px-2 active:cursor-grabbing")}
          onDragStart={(event) => {
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", key);
            clearDragImage.current?.();
            clearDragImage.current = setEntryDragImage(
              event.currentTarget,
              event.dataTransfer,
              event.clientX,
              event.clientY,
            );
            setDragging({ sourceId: section.id, key, kind: section.kind });
          }}
          onDragEnd={() => {
            clearDragImage.current?.();
            clearDragImage.current = null;
            setDragging(null);
          }}
        >
          <span aria-hidden="true">⠿</span>
        </button>
      )}
    </div>
  );
}
