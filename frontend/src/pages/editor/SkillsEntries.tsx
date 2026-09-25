import { ChipListField } from "../../components/ChipListField";
import { AddButton, EntryControls } from "../../components/ListControls";
import { TextField } from "./TextField";
import {
  type Section,
  type SkillGroup,
  type SkillsSection as SkillsSectionData,
  blankSkillGroup,
  moveItem,
  removeAt,
} from "../../lib/resumeEdit";

export function SkillsEntries({
  section,
  pushUndo,
  onChange,
}: {
  section: SkillsSectionData;
  pushUndo: (message: string) => void;
  onChange: (next: Section) => void;
}) {
  const groups = section.entries;
  function setGroups(next: SkillGroup[]) {
    onChange({ ...section, entries: next });
  }

  function removeGroup(idx: number) {
    pushUndo(`Removed “${groups[idx]?.label.trim() || "skill group"}”`);
    setGroups(removeAt(groups, idx));
  }

  return (
    <div className="space-y-4">
      <AddButton label="Add group" onClick={() => setGroups([blankSkillGroup(), ...groups])} />
      <div className="divide-y divide-line">
        {groups.map((g, i) => {
          return (
            <div key={g._key ?? i} className="py-4 first:pt-0 last:pb-0">
              <div className="mb-2 flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <TextField
                    label="Label"
                    value={g.label}
                    onChange={(v) => {
                      const next = [...groups];
                      next[i] = { ...g, label: v };
                      setGroups(next);
                    }}
                  />
                </div>
                <EntryControls
                  index={i}
                  total={groups.length}
                  onMove={(from, to) => setGroups(moveItem(groups, from, to))}
                  onRemove={removeGroup}
                />
              </div>
              <ChipListField
                label="Items"
                items={g.items}
                onChange={(items) => {
                  const next = [...groups];
                  next[i] = { ...g, items };
                  setGroups(next);
                }}
                placeholder="Add a skill"
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
