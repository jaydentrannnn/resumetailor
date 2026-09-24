import { useEffect, useRef, useState } from "react";
import { ChipListField } from "../components/ChipListField";
import { ImportResumePanel } from "../components/ImportResumePanel";
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
import { useConfirm } from "../state/confirmState";
import { useEditorState } from "../state/editorState";

type UndoToast = { id: number; message: string; snapshot: MasterResume };

/**
 * Structured editor for data/master_resume.json — validates through the real Pydantic models.
 *
 * Draft state lives in `EditorProvider` so unsaved edits survive a switch to the Tailor tab.
 * Sections are an ordered, arbitrary-length list (`resume.sections`) — any number of
 * experience-like, project-like, plain-list, education, or skills sections, in any order,
 * under any title. This page never assumes exactly one of each kind.
 */
export function EditorPage({ showContact = true }: { showContact?: boolean }) {
  const {
    resume,
    setResume,
    config,
    errors,
    message,
    busy,
    dirty,
    validate: onValidate,
    save: onSave,
  } = useEditorState();

  const tagVocab = new Set([...(resume?.tag_vocabulary ?? []), ...(config?.tag_vocabulary ?? [])]);
  const vocabList = [...tagVocab].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));

  const takenBulletIds = resume ? collectBulletIds(resume) : new Set<string>();
  const takenEntryIds = resume ? collectEntryIds(resume) : new Set<string>();

  const [toasts, setToasts] = useState<UndoToast[]>([]);
  const nextToastId = useRef(0);
  const timersRef = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  // Mirrors `resume` between renders so a removal handler several components deep
  // (which only has its own section, not the full document) can still snapshot the
  // whole resume for Undo without every list component threading `resume` itself.
  const resumeRef = useRef(resume);
  useEffect(() => {
    resumeRef.current = resume;
  }, [resume]);

  useEffect(
    () => () => {
      for (const timer of timersRef.current.values()) clearTimeout(timer);
    },
    [],
  );

  function dismissToast(id: number) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }

  /**
   * Register an already-applied removal for Undo. Nothing in this editor persists
   * until the explicit Save button, so a confirmation modal on every row delete was
   * asking the user to confirm an edit to their own draft — this replaces that with
   * optimistic delete + a 6s Undo, restoring the exact pre-removal resume snapshot.
   * Callers invoke this *before* applying their own removal, in the same synchronous
   * click handler — `resumeRef` only updates via the effect above, which runs after
   * this handler returns, so it still holds the pre-removal value at capture time.
   */
  function pushUndo(message: string) {
    if (!resumeRef.current) return;
    const snapshot = resumeRef.current;
    const id = nextToastId.current++;
    setToasts((prev) => [...prev, { id, message, snapshot }]);
    timersRef.current.set(
      id,
      setTimeout(() => dismissToast(id), 6000),
    );
  }

  function undoToast(id: number) {
    const toast = toasts.find((t) => t.id === id);
    if (toast) setResume(toast.snapshot);
    dismissToast(id);
  }

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
    <>
      <div className="space-y-6">
        {/* bg-panel (not bg-paper/85) so the sticky bar reads as a toolbar sitting
          above the page, not a translucent cream-on-cream band that only shows
          up as a faint seam. shadow-sm carries the same "this is elevated"
          signal the rest of the app's panels use. */}
        <div className="sticky top-0 z-20 -mx-6 border-b border-line bg-panel px-6 py-3 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="font-display text-2xl font-semibold">Master resume</h1>
              <p className="text-sm text-ink-muted">
                Every fact a tailored resume can use lives here. Tags double as the fabrication
                guard&apos;s whitelist.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {dirty && (
                <span className="rounded-full bg-warn-soft px-2.5 py-1 text-xs font-medium text-warn">
                  Unsaved changes
                </span>
              )}
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
                className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-on-accent disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </div>
          {message && (
            <p
              role="status"
              aria-live="polite"
              className="mt-2 max-h-32 overflow-y-auto rounded-md bg-accent-soft px-3 py-2 text-sm text-accent"
            >
              {message}
            </p>
          )}
          {errors.length > 0 && (
            <ul
              role="alert"
              className="mt-2 max-h-32 overflow-y-auto rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
            >
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </div>

        <details className="rounded-lg border border-line bg-panel p-4">
          <summary className="cursor-pointer text-sm font-medium text-accent">
            Import resume content
          </summary>
          <div className="mt-3">
            <ImportResumePanel />
          </div>
        </details>

        <TagVocabularyPanel resume={resume} onChange={setResume} />

        {showContact && (
          <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <h2 className="font-display text-lg font-semibold">Contact</h2>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <TextField
                label="Name"
                value={resume.contact.name}
                onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, name: v } })}
              />
              <TextField
                label="Email"
                value={resume.contact.email}
                onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, email: v } })}
              />
              <TextField
                label="Phone"
                value={resume.contact.phone ?? ""}
                onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, phone: v } })}
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
        )}

        <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:items-start lg:gap-5">
          <label className="mb-3 block text-sm lg:hidden">
            Jump to section
            <select
              className="field mt-1"
              defaultValue=""
              onChange={(event) =>
                document
                  .getElementById(`resume-section-${event.target.value}`)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              <option value="" disabled>
                Choose a section
              </option>
              {resume.sections.map((section) => (
                <option key={section.id} value={section.id}>
                  {section.title || SECTION_KIND_LABELS[section.kind]}
                </option>
              ))}
            </select>
          </label>
          <nav aria-label="Resume sections" className="sticky top-4 hidden space-y-1 lg:block">
            {resume.sections.map((section) => (
              <a
                key={section.id}
                href={`#resume-section-${section.id}`}
                className="block rounded-md px-2 py-1.5 text-sm text-ink-muted hover:bg-accent-soft hover:text-accent"
              >
                {section.title || SECTION_KIND_LABELS[section.kind]}
              </a>
            ))}
          </nav>
          <div className="space-y-5">
            {resume.sections.map((section, i) => (
              <div key={section.id} id={`resume-section-${section.id}`} className="scroll-mt-4">
                <SectionShell
                  key={section.id}
                  section={section}
                  index={i}
                  total={resume.sections.length}
                  vocabList={vocabList}
                  takenBulletIds={takenBulletIds}
                  takenEntryIds={takenEntryIds}
                  onEnsureVocab={ensureVocab}
                  pushUndo={pushUndo}
                  onRemove={(idx) => {
                    const removedTitle = resume.sections[idx]?.title || "section";
                    pushUndo(`Removed “${removedTitle}”`);
                    setResume((prev) => ({ ...prev, sections: removeAt(prev.sections, idx) }));
                  }}
                  onMove={(from, to) =>
                    setResume((prev) => ({ ...prev, sections: moveItem(prev.sections, from, to) }))
                  }
                  onChange={(next) => updateSection(i, next)}
                />
              </div>
            ))}
          </div>
        </div>

        <p className="text-xs text-ink-muted">
          Reordering sections changes bullet scoring order — the next Tailor run will re-score once
          (one extra LLM call) before using the new order.
        </p>

        <AddSectionPanel onAdd={addSection} />
      </div>
      {toasts.length > 0 && (
        <div className="fixed inset-x-0 bottom-4 z-30 flex flex-col items-center gap-2 px-4 sm:items-end sm:pr-6">
          {toasts.map((t) => (
            <div
              key={t.id}
              role="status"
              className="flex items-center gap-3 rounded-lg border border-line bg-panel px-4 py-2.5 text-sm text-ink shadow-lg"
            >
              <span>{t.message}</span>
              <button
                type="button"
                onClick={() => undoToast(t.id)}
                className="font-semibold text-accent underline-offset-2 hover:underline"
              >
                Undo
              </button>
            </div>
          ))}
        </div>
      )}
    </>
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
          className="rounded-md border border-line bg-paper/40 px-2 py-1.5 text-sm focus:border-accent"
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
  total,
  vocabList,
  takenBulletIds,
  takenEntryIds,
  onEnsureVocab,
  pushUndo,
  onRemove,
  onMove,
  onChange,
}: {
  section: Section;
  index: number;
  total: number;
  vocabList: string[];
  takenBulletIds: Set<string>;
  takenEntryIds: Set<string>;
  onEnsureVocab: (token: string) => void;
  pushUndo: (message: string) => void;
  onRemove: (index: number) => void;
  onMove: (from: number, to: number) => void;
  onChange: (next: Section) => void;
}) {
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
              className="w-full max-w-sm rounded-md border border-line bg-paper/40 px-2 py-1.5 font-display text-lg font-semibold focus:border-accent"
            />
            <span className="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
              {SECTION_KIND_LABELS[section.kind]}
            </span>
          </div>
          <code className="mt-1 block text-xs text-ink-muted">{section.id}</code>
        </div>
        <EntryControls index={index} total={total} onMove={onMove} onRemove={onRemove} />
      </div>

      {section.kind === "experience" && (
        <ExperienceEntries
          section={section}
          vocabList={vocabList}
          takenBulletIds={takenBulletIds}
          takenEntryIds={takenEntryIds}
          onEnsureVocab={onEnsureVocab}
          pushUndo={pushUndo}
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
          pushUndo={pushUndo}
          onChange={onChange}
        />
      )}
      {section.kind === "list" && (
        <ListEntries section={section} pushUndo={pushUndo} onChange={onChange} />
      )}
      {section.kind === "education" && (
        <EducationEntries section={section} pushUndo={pushUndo} onChange={onChange} />
      )}
      {section.kind === "skills" && (
        <SkillsEntries section={section} pushUndo={pushUndo} onChange={onChange} />
      )}
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
  const { confirm } = useConfirm();
  const vocab = resume.tag_vocabulary ?? [];

  async function applyVocabulary(next: string[]) {
    /** Diff against current vocab; removals strip the tag from every bullet. */
    const nextLower = new Set(next.map((t) => t.toLowerCase()));
    const removed = vocab.filter((t) => !nextLower.has(t.toLowerCase()));
    const inUse = removed
      .map((tag) => ({ tag, used: countTagUsage(resume, tag) }))
      .filter((r) => r.used > 0);

    if (inUse.length > 0) {
      const lines = inUse.map((r) => `• "${r.tag}" on ${r.used} bullet(s)`).join("\n");
      const ok = await confirm({
        title: "Remove tags from bullets?",
        message: `These tags are in use and will be stripped from every bullet that uses them:\n\n${lines}`,
        confirmLabel: "Remove from vocabulary and bullets",
        tone: "danger",
      });
      if (!ok) return;
    }

    let updated: MasterResume = { ...resume, tag_vocabulary: next };
    for (const tag of removed) {
      updated = removeTagFromResume(updated, tag);
      updated = {
        ...updated,
        tag_vocabulary: next.filter((t) => t.toLowerCase() !== tag.toLowerCase()),
      };
    }
    onChange(updated);
  }

  return (
    <details className="group rounded-xl border border-line bg-panel p-5 shadow-sm">
      {/* Closed by default — this is a shared option list (settings), not resume
          content, and at ~150 tags it would otherwise dominate the page above
          Contact and every actual section. `list-none` + a manual marker keeps
          the disclosure triangle in the design system's own voice instead of the
          browser default. */}
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
        <span>
          <span className="font-display text-lg font-semibold">Tag options</span>
          <span className="ml-2 text-sm text-ink-muted">
            {vocab.length} tag{vocab.length === 1 ? "" : "s"}
          </span>
        </span>
        <span className="text-ink-muted transition-transform duration-[var(--dur-short)] ease-out group-open:rotate-180">
          ▾
        </span>
      </summary>
      <p className="mt-2 text-sm text-ink-muted">
        Shared list for bullet tags. Adding a tag on a bullet also adds it here; removing an option
        strips it from every bullet that uses it.
      </p>
      <div className="mt-3">
        <ChipListField
          label="Vocabulary"
          items={vocab}
          onChange={(items) => void applyVocabulary(items)}
          placeholder="Add a tag option"
        />
      </div>
    </details>
  );
}

function EducationEntries({
  section,
  pushUndo,
  onChange,
}: {
  section: EducationSectionData;
  pushUndo: (message: string) => void;
  onChange: (next: Section) => void;
}) {
  const entries = section.entries;
  function setEntries(next: Education[]) {
    onChange({ ...section, entries: next });
  }
  function removeEntry(idx: number) {
    pushUndo(`Removed ${entries[idx]?.school.trim() || "entry"}`);
    setEntries(removeAt(entries, idx));
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <AddButton label="Add entry" onClick={() => setEntries([blankEducation(), ...entries])} />
      </div>
      <div className="divide-y divide-line">
        {entries.map((edu, i) => {
          return (
            <div key={edu._key ?? i} className="py-4 first:pt-0 last:pb-0">
              <div className="mb-3 flex items-start justify-between gap-2">
                <p className="text-sm font-medium text-ink-muted">
                  {edu.school.trim() || `Entry #${i + 1}`}
                </p>
                <EntryControls
                  index={i}
                  total={entries.length}
                  onMove={(from, to) => setEntries(moveItem(entries, from, to))}
                  onRemove={removeEntry}
                />
              </div>
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
                    next[i] = { ...edu, dates: v };
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
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ExperienceEntries({
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

function ProjectEntries({
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

function ListEntries({
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

function SkillsEntries({
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

function BulletList({
  bullets,
  vocabList,
  takenIds,
  entryName,
  onEnsureVocab,
  pushUndo,
  onChange,
}: {
  bullets: Bullet[];
  vocabList: string[];
  takenIds: Set<string>;
  entryName: string;
  onEnsureVocab: (token: string) => void;
  pushUndo: (message: string) => void;
  onChange: (b: Bullet[]) => void;
}) {
  const { config } = useEditorState();
  const softMin = config?.bullet_char_soft_min ?? 172;
  const charMax = config?.bullet_char_max ?? 197;

  function addBullet() {
    const prefix = entryPrefix(bullets, entryName);
    const id = nextBulletId(prefix, takenIds);
    onChange(insertAt(bullets, 0, blankBullet(id)));
  }

  function removeBullet(idx: number) {
    const text = bullets[idx]?.text.trim();
    pushUndo(
      `Removed bullet${text ? ` “${text.slice(0, 40)}${text.length > 40 ? "…" : ""}”` : ""}`,
    );
    onChange(removeAt(bullets, idx));
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
        const len = b.text.length;
        const overMax = len >= charMax;
        return (
          <div key={b.id} className="border-l-2 border-line/60 pl-4">
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
                  onMove={(from, to) => onChange(moveItem(bullets, from, to))}
                  onRemove={removeBullet}
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
              className="w-full rounded-md border border-line bg-panel px-2 py-1.5 text-sm focus:border-accent"
            />
            <p
              className={`mt-1 text-xs tabular-nums ${
                overMax ? "text-warn" : len >= softMin ? "text-accent" : "text-ink-muted"
              }`}
            >
              {len} / {charMax}
              {overMax
                ? " — likely to wrap onto a near-empty line"
                : len >= softMin
                  ? " (in target band)"
                  : ""}
            </p>
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
        className="w-full rounded-md border border-line bg-paper/40 px-2 py-1.5 text-sm focus:border-accent"
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
    const re = new RegExp(`(?:^|[^a-z0-9])${escapeReg(tag.toLowerCase())}(?:[^a-z0-9]|$)`);
    if (re.test(lower)) hits.push(tag);
  }
  return hits.slice(0, 8);
}

function escapeReg(s: string): string {
  /** Escape a string for safe use inside a RegExp. */
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
