import { AddButton, EntryControls } from "../../components/ListControls";
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
    setEntries(insertAt(entries, 0, blankListItem(id)));
  }

  function removeItem(idx: number) {
    pushUndo(`Removed “${entries[idx]?.text.trim() || "line"}”`);
    setEntries(removeAt(entries, idx));
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-ink-muted">
          Plain bullet lines — never rewritten or resized, always shown in full.
        </p>
        <AddButton label="Add line" onClick={addItem} />
      </div>
      {entries.map((item, i) => {
        return (
          <div key={item.id} className="flex items-start gap-2">
            <input
              type="text"
              value={item.text}
              onChange={(e) => {
                const next = [...entries];
                next[i] = { ...item, text: e.target.value };
                setEntries(next);
              }}
              placeholder="e.g. AWS Certified Cloud Practitioner"
              className="w-full rounded-md border border-line bg-panel px-2 py-1.5 text-sm focus:border-accent"
            />
            <EntryControls
              index={i}
              total={entries.length}
              onMove={(from, to) => setEntries(moveItem(entries, from, to))}
              onRemove={removeItem}
            />
          </div>
        );
      })}
    </div>
  );
}
