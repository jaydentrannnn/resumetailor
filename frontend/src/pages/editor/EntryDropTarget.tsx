import { useEffect, useState, type ReactNode } from "react";
import type { Section } from "../../lib/resumeEdit";
import { useEntryEditor } from "./EntryEditorContext";

export function EntryDropTarget({ section, children }: { section: Section; children: ReactNode }) {
  const { dragging, setDragging, moveEntry } = useEntryEditor();
  const [over, setOver] = useState(false);
  useEffect(() => {
    if (!dragging) setOver(false);
  }, [dragging]);
  const eligible = dragging?.kind === section.kind && dragging.sourceId !== section.id;
  return (
    <div
      data-entry-drop-target={section.id}
      className={
        eligible ? `rounded-md ring-2 ${over ? "ring-accent" : "ring-accent/30"}` : undefined
      }
      onDragOver={(event) => {
        if (!eligible) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        setOver(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        if (eligible && dragging) moveEntry(dragging.sourceId, dragging.key, section.id);
        setOver(false);
        setDragging(null);
      }}
    >
      {children}
    </div>
  );
}
