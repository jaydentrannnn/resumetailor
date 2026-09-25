import { ChipListField } from "../../components/ChipListField";
import { AddButton, EntryControls } from "../../components/ListControls";
import { BulletList } from "./BulletList";
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
  onEnsureVocab,
  pushUndo,
  onChange,
}: {
  section: ProjectSectionData;
  vocabList: string[];
  takenBulletIds: Set<string>;
  takenEntryIds: Set<string>;
  onEnsureVocab: (token: string) => void;
  pushUndo: (message: string) => void;
  onChange: (next: Section) => void;
}) {
  const entries = section.entries;
  function setEntries(next: Project[]) {
    onChange({ ...section, entries: next });
  }

  function addEntry() {
    const id = nextEntryId("project", "new project", takenEntryIds);
    setEntries(insertAt(entries, 0, blankProject(id)));
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
            <div key={proj.id} className="py-4 first:pt-0 last:pb-0">
              <div className="mb-3 flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-ink-muted">
                    {proj.name.trim() || `Entry #${i + 1}`}
                  </p>
                  <code className="text-xs text-ink-muted">{proj.id}</code>
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
                  label="Name"
                  value={proj.name}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...proj, name: v };
                    setEntries(next);
                  }}
                />
                <TextField
                  label="Date"
                  value={proj.date ?? ""}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...proj, date: v };
                    setEntries(next);
                  }}
                />
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
                <p className="mt-2 text-xs text-warn">
                  Label renders as plain text with no hyperlink — add a GitHub URL.
                </p>
              )}
              {urlLooksOdd && (
                <p className="mt-2 text-xs text-warn">
                  URL should start with http:// or https:// for a working link.
                </p>
              )}
              <BulletList
                bullets={proj.bullets}
                vocabList={vocabList}
                takenIds={takenBulletIds}
                entryName={proj.name}
                onEnsureVocab={onEnsureVocab}
                pushUndo={pushUndo}
                onChange={(bullets) => {
                  const next = [...entries];
                  next[i] = { ...proj, bullets };
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
