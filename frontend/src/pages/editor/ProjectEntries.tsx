import { EntryCard, useEntryEditor } from "./EntryCard";
import { resumeEntryKey } from "../../lib/resumeEntryEdit";
import { ChipListField } from "../../components/ChipListField";
import { AddButton } from "../../components/ListControls";
import { BulletList } from "./BulletList";
import { DateField } from "./DateField";
import { TextField } from "./TextField";
import {
  type Project,
  type ProjectSection as ProjectSectionData,
  type Section,
  blankProject,
  insertAt,
  looksLikeHttpUrl,
  moveItem,
  nextEntryId,
  removeAt,
} from "../../lib/resumeEdit";

export function ProjectEntries({
  section,
  vocabList,
  takenBulletIds,
  takenEntryIds,
  pushUndo,
  onChange,
}: {
  section: ProjectSectionData;
  vocabList: string[];
  takenBulletIds: Set<string>;
  takenEntryIds: Set<string>;
  pushUndo: (message: string) => void;
  onChange: (next: Section) => void;
}) {
  const { setExpanded } = useEntryEditor();
  const entries = section.entries;
  function setEntries(next: Project[]) {
    onChange({ ...section, entries: next });
  }

  function addEntry() {
    const id = nextEntryId("project", "new project", takenEntryIds);
    const entry = blankProject(id);
    setExpanded(resumeEntryKey(entry), true);
    setEntries(insertAt(entries, 0, entry));
  }

  function removeEntry(idx: number) {
    pushUndo(`Removed ${entries[idx]?.name.trim() || "entry"}`);
    setEntries(removeAt(entries, idx));
  }

  return (
    <div className="space-y-4">
      <AddButton label="Add entry" onClick={addEntry} />
      <div className="divide-y divide-line">
        {entries.map((proj, i) => {
          const link = proj.link ?? "";
          const url = proj.url ?? "";
          const linkWithoutUrl = Boolean(link.trim()) && !url.trim();
          const urlLooksOdd = Boolean(url.trim()) && !looksLikeHttpUrl(url);

          return (
            <EntryCard
              key={resumeEntryKey(proj)}
              section={section}
              index={i}
              title={proj.name.trim() || `Entry #${i + 1}`}
              onMove={(from, to) => setEntries(moveItem(entries, from, to))}
              onRemove={removeEntry}
            >
              <code className="mb-3 block text-xs text-ink-muted">{proj.id}</code>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <TextField
                  label="Name"
                  value={proj.name}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...proj, name: v };
                    setEntries(next);
                  }}
                />
                <div className="grid grid-cols-1 gap-3 sm:col-span-2 sm:grid-cols-2">
                  <DateField
                    label="Start"
                    value={proj.start ?? ""}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...proj, start: v, date: "" };
                      setEntries(next);
                    }}
                  />
                  <DateField
                    label="End"
                    allowPresent
                    value={proj.end ?? ""}
                    onChange={(v) => {
                      const next = [...entries];
                      next[i] = { ...proj, end: v, date: "" };
                      setEntries(next);
                    }}
                  />
                  <p className="text-xs text-ink-muted sm:col-span-2">
                    {proj.date?.trim() && !proj.start && !proj.end ? (
                      <>Printed as written: “{proj.date}”. Pick a start (and end) to replace it.</>
                    ) : (
                      "Leave End empty, or the same as Start, to print a single date."
                    )}
                  </p>
                </div>
                <div className="sm:col-span-2">
                  <ChipListField
                    label="Tech"
                    items={proj.tech ?? []}
                    onChange={(tech) => {
                      const next = [...entries];
                      next[i] = { ...proj, tech };
                      setEntries(next);
                    }}
                    placeholder="Add a technology"
                  />
                </div>
                <TextField
                  label="Link label"
                  value={link}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...proj, link: v };
                    setEntries(next);
                  }}
                />
                <TextField
                  label="GitHub URL"
                  value={url}
                  onChange={(v) => {
                    const next = [...entries];
                    const nextLink = v.trim() && !link.trim() ? "Github" : proj.link;
                    next[i] = { ...proj, url: v, link: nextLink };
                    setEntries(next);
                  }}
                />
              </div>
              {linkWithoutUrl && (
                <p className="mt-2 text-xs text-attn">
                  Label renders as plain text with no hyperlink — add a GitHub URL.
                </p>
              )}
              {urlLooksOdd && (
                <p className="mt-2 text-xs text-attn">
                  URL should start with http:// or https:// for a working link.
                </p>
              )}
              <BulletList
                bullets={proj.bullets}
                vocabList={vocabList}
                takenIds={takenBulletIds}
                entryName={proj.name}
                pushUndo={pushUndo}
                onChange={(bullets) => {
                  const next = [...entries];
                  next[i] = { ...proj, bullets };
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
