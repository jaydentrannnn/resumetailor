import { EntryCard, useEntryEditor } from "./EntryCard";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";
import { ChipListField } from "../../components/ChipListField";
import { AddButton } from "../../components/ListControls";
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
  const { setExpanded } = useEntryEditor();
  const groups = section.entries;
  function setGroups(next: SkillGroup[]) {
    onChange({ ...section, entries: next });
  }

  function removeGroup(idx: number) {
    pushUndo(`Removed “${groups[idx]?.label.trim() || "skill group"}”`);
    setGroups(removeAt(groups, idx));
  }

  function addGroup() {
    const group = blankSkillGroup();
    setExpanded(resumeEntryKey(group), true);
    setGroups([group, ...groups]);
  }

  return (
    <div className="space-y-4">
      <AddButton label="Add group" onClick={addGroup} />
      <div className="divide-y divide-line">
        {groups.map((g, i) => {
          return (
            <EntryCard
              key={resumeEntryKey(g)}
              section={section}
              index={i}
              title={g.label.trim() || `Skill group #${i + 1}`}
              onMove={(from, to) => setGroups(moveItem(groups, from, to))}
              onRemove={removeGroup}
            >
              <div className="mb-3">
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
            </EntryCard>
          );
        })}
      </div>
    </div>
  );
}
