import { createContext, useContext, useId, useState, type ReactNode } from "react";
import { EntryControls } from "../../components/ListControls";
import { SECTION_KIND_LABELS, type Section } from "../../lib/resumeEdit";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";

type EntryEditorState = {
  sections: Section[];
  expanded: Set<string>;
  setExpanded: (key: string, open: boolean) => void;
  moveEntry: (sourceId: string, key: string, destinationId: string) => void;
};

const EntryEditorContext = createContext<EntryEditorState | null>(null);

/** UI state stays above section lists so an entry keeps its expansion when moved. */
export function EntryEditorProvider({
  sections,
  moveEntry,
  children,
}: {
  sections: Section[];
  moveEntry: EntryEditorState["moveEntry"];
  children: ReactNode;
}) {
  const [expanded, setExpandedState] = useState(new Set<string>());
  function setExpanded(key: string, open: boolean) {
    setExpandedState((previous) => {
      const next = new Set(previous);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  }
  return (
    <EntryEditorContext.Provider value={{ sections, expanded, setExpanded, moveEntry }}>
      {children}
    </EntryEditorContext.Provider>
  );
}

export function useEntryEditor() {
  const state = useContext(EntryEditorContext);
  if (!state) throw new Error("Resume entries must be inside EntryEditorProvider");
  return state;
}

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
  const { sections, expanded, setExpanded, moveEntry } = useEntryEditor();
  const key = resumeEntryKey(section.entries[index]);
  const open = expanded.has(key);
  const bodyId = useId();
  const destinations = sections.filter((s) => s.id !== section.id && s.kind === section.kind);

  return (
    <div data-resume-entry className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={`${open ? "Collapse" : "Expand"} ${title}`}
          onClick={() => setExpanded(key, !open)}
          className="flex min-w-0 flex-1 items-center gap-2 rounded py-1 text-left text-sm font-medium hover:text-accent focus-visible:outline-accent"
        >
          <span aria-hidden="true" className="shrink-0">
            {open ? "▾" : "▸"}
          </span>
          <span className="break-words">{title}</span>
        </button>
        <div className="flex flex-wrap items-center gap-2">
          {destinations.length > 0 && (
            <select
              value=""
              aria-label={`Move ${title} to section`}
              onChange={(event) => moveEntry(section.id, key, event.target.value)}
              className="max-w-48 rounded border border-line bg-panel px-2 py-1 text-xs focus:border-accent"
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
          />
        </div>
      </div>
      <div id={bodyId} hidden={!open} className="mt-3">
        {children}
      </div>
    </div>
  );
}
