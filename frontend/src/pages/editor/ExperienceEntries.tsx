import { AddButton, EntryControls } from "../../components/ListControls";
import { BulletList } from "./BulletList";
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
  const entries = section.entries;
  function setEntries(next: Experience[]) {
    onChange({ ...section, entries: next });
  }

  function addEntry() {
    const id = nextEntryId("experience", "new role", takenEntryIds);
    setEntries(insertAt(entries, 0, blankExperience(id)));
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
            <div key={job.id} className="py-4 first:pt-0 last:pb-0">
              <div className="mb-3 flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-ink-muted">
                    {job.company.trim() || `Entry #${i + 1}`}
                  </p>
                  <code className="text-xs text-ink-muted">{job.id}</code>
                </div>
                <EntryControls
                  index={i}
                  total={entries.length}
                  onMove={(from, to) => setEntries(moveItem(entries, from, to))}
                  onRemove={removeEntry}
                />
              </div>
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
                <div className="grid grid-cols-2 gap-3">
                  <TextField
                    label="Start (YYYY-MM)"
                    value={job.start}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...job, start: v };
                      setEntries(next);
                    }}
                  />
                  <TextField
                    label="End"
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
            </div>
          );
        })}
      </div>
    </div>
  );
}
