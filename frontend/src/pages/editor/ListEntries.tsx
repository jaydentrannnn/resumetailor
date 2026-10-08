import { EntryCard, useEntryEditor } from "./EntryCard";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";
import { AddButton } from "../../components/ListControls";
import {
  type ListItem,
  type ListSection as ListSectionData,
  type Section,
  blankListItem,
  insertAt,
  moveItem,
  removeAt,
} from "../../lib/resumeEdit";

export function ListEntries({
  section,
  pushUndo,
  onChange,
}: {
  section: ListSectionData;
  pushUndo: (message: string) => void;
  onChange: (next: Section) => void;
}) {
  const { setExpanded } = useEntryEditor();
  const entries = section.entries;
  function setEntries(next: ListItem[]) {
    onChange({ ...section, entries: next });
  }

  function addItem() {
    const taken = new Set(entries.map((e) => e.id));
    let n = entries.length + 1;
    let id = `item_${n}`;
    while (taken.has(id)) {
      n += 1;
      id = `item_${n}`;
    }
    const item = blankListItem(id);
    setExpanded(resumeEntryKey(item), true);
    setEntries(insertAt(entries, 0, item));
  }

  function removeItem(idx: number) {
    pushUndo(`Removed “${entries[idx]?.text.trim() || "line"}”`);
    setEntries(removeAt(entries, idx));
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-ink-muted">
          Plain bullet lines — never rewritten or resized, always shown in full.
        </p>
        <AddButton label="Add line" onClick={addItem} />
      </div>
      {entries.map((item, i) => {
        return (
          <EntryCard
            key={resumeEntryKey(item)}
            section={section}
            index={i}
            title={item.text.trim() || `Line #${i + 1}`}
            onMove={(from, to) => setEntries(moveItem(entries, from, to))}
            onRemove={removeItem}
          >
            <input
              type="text"
              aria-label="Line text"
              value={item.text}
              onChange={(e) => {
                const next = [...entries];
                next[i] = { ...item, text: e.target.value };
                setEntries(next);
              }}
              placeholder="e.g. AWS Certified Cloud Practitioner"
              className="field"
            />
          </EntryCard>
        );
      })}
    </div>
  );
}
