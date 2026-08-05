import { useState } from "react";
import { ChipListField } from "../components/ChipListField";
import { AddButton, EntryControls } from "../components/ListControls";
import {
  type Bullet,
  type Education,
  type EducationSection as EducationSectionData,
  type Experience,
  type ExperienceSection as ExperienceSectionData,
  type ListItem,
  type ListSection as ListSectionData,
  type MasterResume,
  type Project,
  type ProjectSection as ProjectSectionData,
  type Section,
  type SectionKind,
  type SkillGroup,
  type SkillsSection as SkillsSectionData,
  DEFAULT_SECTION_TITLES,
  SECTION_KIND_LABELS,
  addToVocabulary,
  blankBullet,
  blankEducation,
  blankExperience,
  blankListItem,
  blankProject,
  blankSection,
  blankSkillGroup,
  collectBulletIds,
  collectEntryIds,
  collectSectionIds,
  countTagUsage,
  entryPrefix,
  insertAt,
  looksLikeHttpUrl,
  moveItem,
  nextBulletId,
  nextEntryId,
  nextSectionId,
  removeAt,
  removeTagFromResume,
  uniqueTags,
} from "../lib/resumeEdit";
import { useEditorState } from "../state/editorState";

/**
 * Structured editor for data/master_resume.json — validates through the real Pydantic models.
 *
 * Draft state lives in `EditorProvider` so unsaved edits survive a switch to the Tailor tab.
 * Sections are an ordered, arbitrary-length list (`resume.sections`) — any number of
 * experience-like, project-like, plain-list, education, or skills sections, in any order,
 * under any title. This page never assumes exactly one of each kind.
 */
export function EditorPage() {
  const {
    resume,
    setResume,
    config,
    errors,
    message,
    busy,
    validate: onValidate,
    save: onSave,
  } = useEditorState();

  const tagVocab = new Set([
    ...(resume?.tag_vocabulary ?? []),
    ...(config?.tag_vocabulary ?? []),
  ]);
  const vocabList = [...tagVocab].sort((a, b) =>
    a.toLowerCase().localeCompare(b.toLowerCase()),
  );

  const takenBulletIds = resume ? collectBulletIds(resume) : new Set<string>();
  const takenEntryIds = resume ? collectEntryIds(resume) : new Set<string>();

  if (!resume) {
    return (
      <p className="text-sm text-ink-muted">
        {errors.length ? errors.join("; ") : "Loading master resume…"}
      </p>
    );
  }

  function ensureVocab(token: string) {
    /** Promote a newly typed tag into the stored vocabulary list. */
    setResume((prev) => ({
      ...prev,
      tag_vocabulary: addToVocabulary(prev.tag_vocabulary ?? [], token),
    }));
  }

  function updateSection(index: number, next: Section) {
    setResume((prev) => {
      const sections = [...prev.sections];
      sections[index] = next;
      return { ...prev, sections };
    });
  }

  function addSection(kind: SectionKind) {
    setResume((prev) => {
      const id = nextSectionId(DEFAULT_SECTION_TITLES[kind], kind, collectSectionIds(prev));
      return { ...prev, sections: [...prev.sections, blankSection(id, kind)] };
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold">Master resume</h1>
          <p className="text-sm text-ink-muted">
            Every fact a tailored resume can use lives here. Tags double as the fabrication
            guard&apos;s whitelist.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onValidate}
            disabled={busy}
            className="rounded-md border border-line px-3 py-2 text-sm font-medium hover:border-accent disabled:opacity-50"
          >
            Validate
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={busy}
            className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>

      {message && (
        <p className="rounded-md bg-accent-soft px-3 py-2 text-sm text-accent">{message}</p>
      )}
      {errors.length > 0 && (
        <ul className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}

      <TagVocabularyPanel resume={resume} onChange={setResume} />

      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
        <h2 className="font-display text-lg font-semibold">Contact</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <TextField
            label="Name"
            value={resume.contact.name}
            onChange={(v) =>
              setResume({ ...resume, contact: { ...resume.contact, name: v } })
            }
          />
          <TextField
            label="Email"
            value={resume.contact.email}
            onChange={(v) =>
              setResume({ ...resume, contact: { ...resume.contact, email: v } })
            }
          />
          <TextField
            label="Phone"
            value={resume.contact.phone ?? ""}
            onChange={(v) =>
              setResume({ ...resume, contact: { ...resume.contact, phone: v } })
            }
          />
          <TextField
            label="Location"
            value={resume.contact.location ?? ""}
            onChange={(v) =>
              setResume({ ...resume, contact: { ...resume.contact, location: v } })
            }
          />
          <TextField
            label="LinkedIn URL"
            value={resume.contact.linkedin ?? ""}
            onChange={(v) =>
              setResume({ ...resume, contact: { ...resume.contact, linkedin: v } })
            }
          />
          <TextField
            label="GitHub URL"
            value={resume.contact.github ?? ""}
            onChange={(v) =>
              setResume({ ...resume, contact: { ...resume.contact, github: v } })
            }
          />
        </div>
        {(resume.contact.linkedin ?? "").trim() &&
          !looksLikeHttpUrl(resume.contact.linkedin ?? "") && (
            <p className="mt-2 text-xs text-warn">
              LinkedIn URL should start with http:// or https://.
            </p>
          )}
        {(resume.contact.github ?? "").trim() &&
          !looksLikeHttpUrl(resume.contact.github ?? "") && (
            <p className="mt-2 text-xs text-warn">
              GitHub URL should start with http:// or https://.
            </p>
          )}
      </section>

      {resume.sections.map((section, i) => (
        <SectionShell
          key={section.id}
          section={section}
          index={i}
          vocabList={vocabList}
          takenBulletIds={takenBulletIds}
          takenEntryIds={takenEntryIds}
          onEnsureVocab={ensureVocab}
          onRemove={(idx) =>
            setResume((prev) => ({ ...prev, sections: removeAt(prev.sections, idx) }))
          }
          onChange={(next) => updateSection(i, next)}
        />
      ))}

      <AddSectionPanel onAdd={addSection} />
    </div>
  );
}

function AddSectionPanel({ onAdd }: { onAdd: (kind: SectionKind) => void }) {
  const kinds: SectionKind[] = ["experience", "project", "list", "education", "skills"];
  const [kind, setKind] = useState<SectionKind>("experience");

  return (
    <section className="flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-line p-4">
      <label className="text-sm text-ink-muted">
        <span className="mr-2">New section:</span>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as SectionKind)}
          className="rounded-md border border-line bg-paper/40 px-2 py-1.5 text-sm outline-none focus:border-accent"
        >
          {kinds.map((k) => (
            <option key={k} value={k}>
              {SECTION_KIND_LABELS[k]}
            </option>
          ))}
        </select>
      </label>
      <AddButton label="Add section" onClick={() => onAdd(kind)} />
    </section>
  );
}

function SectionShell({
  section,
  index,
  vocabList,
  takenBulletIds,
  takenEntryIds,
  onEnsureVocab,
  onRemove,
  onChange,
}: {
  section: Section;
  index: number;
  vocabList: string[];
  takenBulletIds: Set<string>;
  takenEntryIds: Set<string>;
  onEnsureVocab: (token: string) => void;
  onRemove: (index: number) => void;
  onChange: (next: Section) => void;
}) {
  const hasContent = section.entries.length > 0;

  return (
    <section className="space-y-4 rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={section.title}
              onChange={(e) => onChange({ ...section, title: e.target.value } as Section)}
              placeholder="Section title"
              className="w-full max-w-sm rounded-md border border-line bg-paper/40 px-2 py-1.5 font-display text-lg font-semibold outline-none focus:border-accent"
            />
            <span className="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
              {SECTION_KIND_LABELS[section.kind]}
            </span>
          </div>
          <code className="mt-1 block text-xs text-ink-muted">{section.id}</code>
        </div>
        <EntryControls
          index={index}
          total={1}
          hasContent={hasContent}
          label={section.title}
          canMove={false}
          onMove={() => {}}
          onRemove={onRemove}
        />
      </div>

      {section.kind === "experience" && (
        <ExperienceEntries
          section={section}
          vocabList={vocabList}
          takenBulletIds={takenBulletIds}
          takenEntryIds={takenEntryIds}
          onEnsureVocab={onEnsureVocab}
          onChange={onChange}
        />
      )}
      {section.kind === "project" && (
        <ProjectEntries
          section={section}
          vocabList={vocabList}
          takenBulletIds={takenBulletIds}
          takenEntryIds={takenEntryIds}
          onEnsureVocab={onEnsureVocab}
          onChange={onChange}
        />
      )}
      {section.kind === "list" && <ListEntries section={section} onChange={onChange} />}
      {section.kind === "education" && (
        <EducationEntries section={section} onChange={onChange} />
      )}
      {section.kind === "skills" && <SkillsEntries section={section} onChange={onChange} />}
    </section>
  );
}

function TagVocabularyPanel({
  resume,
  onChange,
}: {
  resume: MasterResume;
  onChange: (r: MasterResume) => void;
}) {
  /**
   * Manage the shared tag option list. Removing an in-use option strips it from
   * every bullet after confirmation — tags are the fabrication guard's whitelist.
   */
  const vocab = resume.tag_vocabulary ?? [];

  function applyVocabulary(next: string[]) {
    /** Diff against current vocab; removals strip the tag from every bullet. */
    const nextLower = new Set(next.map((t) => t.toLowerCase()));
    const removed = vocab.filter((t) => !nextLower.has(t.toLowerCase()));
    let updated: MasterResume = { ...resume, tag_vocabulary: next };
    for (const tag of removed) {
      const used = countTagUsage(resume, tag);
      if (used > 0) {
        const ok = window.confirm(
          `"${tag}" is on ${used} bullet(s). Remove it from the vocabulary and those bullets?`,
        );
        if (!ok) {
          // Keep the tag in the list; abort this removal only.
          updated = {
            ...updated,
            tag_vocabulary: addToVocabulary(updated.tag_vocabulary ?? [], tag),
          };
          continue;
        }
      }
      updated = removeTagFromResume(updated, tag);
      // removeTagFromResume also drops it from vocab; re-apply any newly added tokens.
      updated = {
        ...updated,
        tag_vocabulary: next.filter((t) => t.toLowerCase() !== tag.toLowerCase()),
      };
    }
    onChange(updated);
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <h2 className="font-display text-lg font-semibold">Tag options</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Shared list for bullet tags. Adding a tag on a bullet also adds it here; removing
        an option strips it from every bullet that uses it.
      </p>
      <div className="mt-3">
        <ChipListField
          label="Vocabulary"
          items={vocab}
          onChange={applyVocabulary}
          placeholder="Add a tag option"
        />
      </div>
    </section>
  );
}

function EducationEntries({
  section,
  onChange,
}: {
  section: EducationSectionData;
  onChange: (next: Section) => void;
}) {
  const entries = section.entries;
  function setEntries(next: Education[]) {
    onChange({ ...section, entries: next });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <AddButton
          label="Add entry"
          onClick={() => setEntries([blankEducation(), ...entries])}
        />
      </div>
      {entries.map((edu, i) => {
        const hasContent = Boolean(
          edu.school.trim() ||
            edu.degree.trim() ||
            (edu.coursework?.length ?? 0) ||
            (edu.details?.length ?? 0),
        );
        return (
          <div key={i} className="rounded-lg border border-line/80 bg-paper/40 p-3">
            <div className="mb-3 flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-ink-muted">
                {edu.school.trim() || `Entry #${i + 1}`}
              </p>
              <EntryControls
                index={i}
                total={entries.length}
                hasContent={hasContent}
                label={edu.school}
                onMove={(from, to) => setEntries(moveItem(entries, from, to))}
                onRemove={(idx) => setEntries(removeAt(entries, idx))}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
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
                  next[i] = { ...edu, dates: v };
                  setEntries(next);
                }}
              />
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
                    className="w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm outline-none focus:border-accent"
                  />
                  <button
                    type="button"
                    title="Remove detail"
                    onClick={() => {
                      const details = (edu.details ?? []).filter((_, j) => j !== di);
                      const next = [...entries];
                      next[i] = { ...edu, details };
                      setEntries(next);
                    }}
                    className="shrink-0 rounded border border-line px-2 py-0.5 text-xs text-danger hover:border-danger"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ExperienceEntries({
  section,
  vocabList,
  takenBulletIds,
  takenEntryIds,
  onEnsureVocab,
  onChange,
}: {
  section: ExperienceSectionData;
  vocabList: string[];
  takenBulletIds: Set<string>;
  takenEntryIds: Set<string>;
  onEnsureVocab: (token: string) => void;
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

  return (
    <div className="space-y-4">
      <AddButton label="Add entry" onClick={addEntry} />
      {entries.map((job, i) => {
        const hasContent =
          Boolean(job.company.trim() || job.title.trim() || job.bullets.length);
        return (
          <div key={i} className="rounded-lg border border-line/80 bg-paper/40 p-3">
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
                hasContent={hasContent}
                label={job.company}
                onMove={(from, to) => setEntries(moveItem(entries, from, to))}
                onRemove={(idx) => setEntries(removeAt(entries, idx))}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
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
  );
}

function ProjectEntries({
  section,
  vocabList,
  takenBulletIds,
  takenEntryIds,
  onEnsureVocab,
  onChange,
}: {
  section: ProjectSectionData;
  vocabList: string[];
  takenBulletIds: Set<string>;
  takenEntryIds: Set<string>;
  onEnsureVocab: (token: string) => void;
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

  return (
    <div className="space-y-4">
      <AddButton label="Add entry" onClick={addEntry} />
      {entries.map((proj, i) => {
        const hasContent =
          Boolean(proj.name.trim() || proj.url?.trim() || proj.bullets.length);
        const link = proj.link ?? "";
        const url = proj.url ?? "";
        const linkWithoutUrl = Boolean(link.trim()) && !url.trim();
        const urlLooksOdd = Boolean(url.trim()) && !looksLikeHttpUrl(url);

        return (
          <div key={i} className="rounded-lg border border-line/80 bg-paper/40 p-3">
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
                hasContent={hasContent}
                label={proj.name}
                onMove={(from, to) => setEntries(moveItem(entries, from, to))}
                onRemove={(idx) => setEntries(removeAt(entries, idx))}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
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
  );
}

function ListEntries({
  section,
  onChange,
}: {
  section: ListSectionData;
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

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-ink-muted">
          Plain bullet lines — never rewritten or resized, always shown in full.
        </p>
        <AddButton label="Add line" onClick={addItem} />
      </div>
      {entries.map((item, i) => {
        const hasContent = Boolean(item.text.trim());
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
              className="w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
            <EntryControls
              index={i}
              total={entries.length}
              hasContent={hasContent}
              label={item.text || "this line"}
              onMove={(from, to) => setEntries(moveItem(entries, from, to))}
              onRemove={(idx) => setEntries(removeAt(entries, idx))}
            />
          </div>
        );
      })}
    </div>
  );
}

function SkillsEntries({
  section,
  onChange,
}: {
  section: SkillsSectionData;
  onChange: (next: Section) => void;
}) {
  const groups = section.entries;
  function setGroups(next: SkillGroup[]) {
    onChange({ ...section, entries: next });
  }

  return (
    <div className="space-y-4">
      <AddButton label="Add group" onClick={() => setGroups([blankSkillGroup(), ...groups])} />
      {groups.map((g, i) => {
        const hasContent = Boolean(g.label.trim() || g.items.length);
        return (
          <div key={i} className="rounded-lg border border-line/80 bg-paper/40 p-3">
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
                hasContent={hasContent}
                label={g.label || "skill group"}
                onMove={(from, to) => setGroups(moveItem(groups, from, to))}
                onRemove={(idx) => setGroups(removeAt(groups, idx))}
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
  );
}

function BulletList({
  bullets,
  vocabList,
  takenIds,
  entryName,
  onEnsureVocab,
  onChange,
}: {
  bullets: Bullet[];
  vocabList: string[];
  takenIds: Set<string>;
  entryName: string;
  onEnsureVocab: (token: string) => void;
  onChange: (b: Bullet[]) => void;
}) {
  function addBullet() {
    const prefix = entryPrefix(bullets, entryName);
    const id = nextBulletId(prefix, takenIds);
    onChange(insertAt(bullets, 0, blankBullet(id)));
  }

  const vocabSet = new Set(vocabList.map((t) => t.toLowerCase()));

  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-ink-muted">Bullets</h3>
        <AddButton label="Add bullet" onClick={addBullet} />
      </div>
      {bullets.map((b, i) => {
        const missing = suggestMissingTags(b.text, b.tags, vocabSet, vocabList);
        const hasContent = Boolean(b.text.trim() || b.tags.length);
        return (
          <div key={b.id} className="rounded-lg border border-line/80 bg-paper/40 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
              <code>{b.id}</code>
              <div className="flex items-center gap-2">
                <label className="inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={Boolean(b.metric)}
                    onChange={(e) => {
                      const next = [...bullets];
                      next[i] = { ...b, metric: e.target.checked };
                      onChange(next);
                    }}
                  />
                  has metric
                </label>
                <EntryControls
                  index={i}
                  total={bullets.length}
                  hasContent={hasContent}
                  label={`bullet ${b.id}`}
                  onMove={(from, to) => onChange(moveItem(bullets, from, to))}
                  onRemove={(idx) => onChange(removeAt(bullets, idx))}
                />
              </div>
            </div>
            <textarea
              value={b.text}
              rows={3}
              onChange={(e) => {
                const next = [...bullets];
                next[i] = { ...b, text: e.target.value };
                onChange(next);
              }}
              className="w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
            <div className="mt-2">
              <ChipListField
                label="Tags"
                items={b.tags}
                suggestions={vocabList}
                onAddNew={onEnsureVocab}
                onChange={(tags) => {
                  const next = [...bullets];
                  next[i] = { ...b, tags: uniqueTags(tags) };
                  onChange(next);
                }}
                placeholder="Add a tag"
              />
            </div>
            {missing.length > 0 && (
              <p className="mt-1 text-xs text-warn">
                Text mentions vocabulary not in tags: {missing.join(", ")}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-ink-muted">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-line bg-paper/40 px-2 py-1.5 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}

function suggestMissingTags(
  text: string,
  tags: string[],
  vocabLower: Set<string>,
  vocabList: string[],
): string[] {
  /**
   * Flag vocabulary words that appear in the bullet text but not its tags.
   * Tags are the fabrication guard's whitelist — a miss here is a future false positive.
   */
  const have = new Set(tags.map((t) => t.toLowerCase()));
  const lower = text.toLowerCase();
  const hits: string[] = [];
  for (const tag of vocabList) {
    if (!vocabLower.has(tag.toLowerCase())) continue;
    if (have.has(tag.toLowerCase())) continue;
    // Whole-word-ish match: avoid flagging "go" inside "google".
    const re = new RegExp(
      `(?:^|[^a-z0-9])${escapeReg(tag.toLowerCase())}(?:[^a-z0-9]|$)`,
    );
    if (re.test(lower)) hits.push(tag);
  }
  return hits.slice(0, 8);
}

function escapeReg(s: string): string {
  /** Escape a string for safe use inside a RegExp. */
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
