import { EntryCard, useEntryEditor } from "./EntryCard";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";
import { AddButton } from "../../components/ListControls";
import { BulletList } from "./BulletList";
import { DateField } from "./DateField";
import { TextField } from "./TextField";
import {
  type Experience,
  type ExperienceSection as ExperienceSectionData,
  type Section,
  blankExperience,
  insertAt,
  moveItem,
  nextEntryId,
  removeAt,
} from "../../lib/resumeEdit";

export function ExperienceEntries({
  section,
  vocabList,
  takenBulletIds,
  takenEntryIds,
  onEnsureVocab,
  pushUndo,
  onChange,
}: {
  section: ExperienceSectionData;
  vocabList: string[];
  takenBulletIds: Set<string>;
  takenEntryIds: Set<string>;
  onEnsureVocab: (token: string) => void;
  pushUndo: (message: string) => void;
  onChange: (next: Section) => void;
}) {
  const { setExpanded } = useEntryEditor();
  const entries = section.entries;
  function setEntries(next: Experience[]) {
    onChange({ ...section, entries: next });
  }

  function addEntry() {
    const id = nextEntryId("experience", "new role", takenEntryIds);
    const entry = blankExperience(id);
    setExpanded(resumeEntryKey(entry), true);
    setEntries(insertAt(entries, 0, entry));
  }

  function removeEntry(idx: number) {
    pushUndo(`Removed ${entries[idx]?.company.trim() || "entry"}`);
    setEntries(removeAt(entries, idx));
  }

  return (
    <div className="space-y-4">
      <AddButton label="Add entry" onClick={addEntry} />
      <div className="divide-y divide-line">
        {entries.map((job, i) => {
          return (
            <EntryCard
              key={resumeEntryKey(job)}
              section={section}
              index={i}
              title={
                [job.company.trim(), job.title.trim()].filter(Boolean).join(" · ") ||
                `Entry #${i + 1}`
              }
              onMove={(from, to) => setEntries(moveItem(entries, from, to))}
              onRemove={removeEntry}
            >
              <code className="mb-3 block text-xs text-ink-muted">{job.id}</code>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <TextField
                  label="Company"
                  value={job.company}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...job, company: v };
                    setEntries(next);
                  }}
                />
                <TextField
                  label="Title"
                  value={job.title}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...job, title: v };
                    setEntries(next);
                  }}
                />
                <div className="grid grid-cols-1 gap-3 sm:col-span-2 sm:grid-cols-2">
                  <DateField
                    label="Start"
                    value={job.start}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...job, start: v };
                      setEntries(next);
                    }}
                  />
                  <DateField
                    label="End"
                    allowPresent
                    value={job.end}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...job, end: v };
                      setEntries(next);
                    }}
                  />
                </div>
                <TextField
                  label="Location"
                  value={job.location ?? ""}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...job, location: v };
                    setEntries(next);
                  }}
                />
              </div>
              <BulletList
                bullets={job.bullets}
                vocabList={vocabList}
                takenIds={takenBulletIds}
                entryName={job.company}
                onEnsureVocab={onEnsureVocab}
                pushUndo={pushUndo}
                onChange={(bullets) => {
                  const next = [...entries];
                  next[i] = { ...job, bullets };
                  setEntries(next);
                }}
              />
            </EntryCard>
          );
        })}
      </div>
    </div>
  );
}
