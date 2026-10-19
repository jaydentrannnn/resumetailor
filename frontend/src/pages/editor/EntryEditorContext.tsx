import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Section } from "../../lib/resumeEdit";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";

export type DraggedEntry = { sourceId: string; key: string; kind: Section["kind"] };
type EntryEditorState = {
  sections: Section[];
  expanded: Set<string>;
  setExpanded: (key: string, open: boolean) => void;
  moveEntry: (sourceId: string, key: string, destinationId: string) => void;
  dragging: DraggedEntry | null;
  setDragging: (entry: DraggedEntry | null) => void;
  /** The page's entry filter (`lib/entryFilter.ts`); empty shows everything. */
  filter: string;
};
const EntryEditorContext = createContext<EntryEditorState | null>(null);

/** Entry identity and expansion survive cross-section transfers. */
export function EntryEditorProvider({
  sections,
  moveEntry,
  filter = "",
  children,
}: {
  sections: Section[];
  moveEntry: EntryEditorState["moveEntry"];
  filter?: string;
  children: ReactNode;
}) {
  const [expanded, setExpandedState] = useState(new Set<string>());
  const [dragging, setDragging] = useState<DraggedEntry | null>(null);
  const [reveal, setReveal] = useState<string | null>(null);
  function setExpanded(key: string, open: boolean) {
    if (
      open &&
      !sections.some((section) => section.entries.some((e) => resumeEntryKey(e) === key))
    ) {
      setReveal(key);
    }
    setExpandedState((previous) => {
      const next = new Set(previous);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  }
  useEffect(() => {
    if (!reveal) return;
    const node = [...document.querySelectorAll<HTMLElement>("[data-entry-key]")].find(
      (element) => element.dataset.entryKey === reveal,
    );
    if (node) {
      node.scrollIntoView?.({ block: "nearest" });
      setReveal(null);
    }
  }, [sections, reveal]);
  return (
    <EntryEditorContext.Provider
      value={{ sections, expanded, setExpanded, moveEntry, dragging, setDragging, filter }}
    >
      {children}
    </EntryEditorContext.Provider>
  );
}

export function useEntryEditor() {
  const state = useContext(EntryEditorContext);
  if (!state) throw new Error("Resume entries must be inside EntryEditorProvider");
  return state;
}
