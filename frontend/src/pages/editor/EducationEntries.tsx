import { EntryCard, useEntryEditor } from "./EntryCard";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";
import { ChipListField } from "../../components/ChipListField";
import { AddButton } from "../../components/ListControls";
import { DateField } from "./DateField";
import { TextField } from "./TextField";
import {
  type Education,
  type EducationSection as EducationSectionData,
  type Section,
  blankEducation,
  moveItem,
  removeAt,
} from "../../lib/resumeEdit";

export function EducationEntries({
  section,
  pushUndo,
  onChange,
}: {
  section: EducationSectionData;
  pushUndo: (message: string) => void;
  onChange: (next: Section) => void;
}) {
  const { setExpanded } = useEntryEditor();
  const entries = section.entries;
  function setEntries(next: Education[]) {
    onChange({ ...section, entries: next });
  }
  function removeEntry(idx: number) {
    pushUndo(`Removed ${entries[idx]?.school.trim() || "entry"}`);
    setEntries(removeAt(entries, idx));
  }

  function addEntry() {
    const entry = blankEducation();
    setExpanded(resumeEntryKey(entry), true);
    setEntries([entry, ...entries]);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <AddButton label="Add entry" onClick={addEntry} />
      </div>
      <div className="divide-y divide-line">
        {entries.map((edu, i) => {
          return (
            <EntryCard
              key={resumeEntryKey(edu)}
              section={section}
              index={i}
              title={edu.school.trim() || `Entry #${i + 1}`}
              onMove={(from, to) => setEntries(moveItem(entries, from, to))}
              onRemove={removeEntry}
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <TextField
                  label="School"
                  value={edu.school}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...edu, school: v };
                    setEntries(next);
                  }}
                />
                <TextField
                  label="Location"
                  value={edu.location ?? ""}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...edu, location: v };
                    setEntries(next);
                  }}
                />
                <TextField
                  label="Degree"
                  value={edu.degree}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...edu, degree: v };
                    setEntries(next);
                  }}
                />
                <TextField
                  label="Dates"
                  value={edu.dates}
                  onChange={(v) => {
                    const next = [...entries];
                    // New printed dates: the months are read again from them on save.
                    next[i] = { ...edu, dates: v, start: "", end: "" };
                    setEntries(next);
                  }}
                />
                <div className="sm:col-span-2">
                  <TextField
                    label="Major (field of study)"
                    value={edu.major ?? ""}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...edu, major: v };
                      setEntries(next);
                    }}
                  />
                  <p className="mt-1 text-xs text-ink-muted">
                    Used to answer application forms; never printed on the resume.
                  </p>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:col-span-2 sm:grid-cols-2">
                  <DateField
                    label="Start"
                    value={edu.start ?? ""}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...edu, start: v };
                      setEntries(next);
                    }}
                  />
                  <DateField
                    label="Expected graduation"
                    value={edu.end ?? ""}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...edu, end: v };
                      setEntries(next);
                    }}
                  />
                  <p className="text-xs text-ink-muted sm:col-span-2">
                    For application forms; the resume prints Dates as written. Left empty, they are
                    read from Dates when you save.
                  </p>
                </div>
                <div className="sm:col-span-2">
                  <TextField
                    label="GPA"
                    value={edu.gpa ?? ""}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...edu, gpa: v };
                      setEntries(next);
                    }}
                  />
                  <p className="mt-1 text-xs text-ink-muted">
                    Whether GPA appears on the resume is set per run on the Tailor tab.
                  </p>
                </div>
              </div>
              <div className="mt-3">
                <ChipListField
                  label="Relevant coursework"
                  items={edu.coursework ?? []}
                  onChange={(coursework) => {
                    const next = [...entries];
                    next[i] = { ...edu, coursework };
                    setEntries(next);
                  }}
                  placeholder="Add a course"
                />
              </div>
              <div className="mt-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-ink-muted">Other detail lines</span>
                  <AddButton
                    label="Add detail"
                    onClick={() => {
                      const next = [...entries];
                      next[i] = { ...edu, details: ["", ...(edu.details ?? [])] };
                      setEntries(next);
                    }}
                  />
                </div>
                {(edu.details ?? []).map((detail, di) => (
                  <div key={di} className="flex gap-2">
                    <input
                      type="text"
                      value={detail}
                      onChange={(e) => {
                        const details = [...(edu.details ?? [])];
                        details[di] = e.target.value;
                        const next = [...entries];
                        next[i] = { ...edu, details };
                        setEntries(next);
                      }}
                      className="w-full rounded-md border border-line bg-panel px-2 py-1.5 text-sm focus:border-accent"
                    />
                    <button
                      type="button"
                      title="Remove detail"
                      aria-label="Remove detail"
                      onClick={() => {
                        const details = (edu.details ?? []).filter((_, j) => j !== di);
                        const next = [...entries];
                        next[i] = { ...edu, details };
                        setEntries(next);
                      }}
                      className="flex min-h-6 min-w-6 shrink-0 items-center justify-center rounded border border-line text-xs text-danger hover:border-danger"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </EntryCard>
          );
        })}
      </div>
    </div>
  );
}
