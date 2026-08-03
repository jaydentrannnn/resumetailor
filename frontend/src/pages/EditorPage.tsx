import { ChipListField } from "../components/ChipListField";
import { AddButton, EntryControls } from "../components/ListControls";
import {
  type Bullet,
  type Education,
  type Experience,
  type MasterResume,
  type Project,
  type SkillGroup,
  addToVocabulary,
  blankBullet,
  blankEducation,
  blankExperience,
  blankProject,
  blankSkillGroup,
  collectBulletIds,
  collectExperienceIds,
  collectProjectIds,
  countTagUsage,
  entryPrefix,
  insertAt,
  looksLikeHttpUrl,
  moveItem,
  nextBulletId,
  nextExperienceId,
  nextProjectId,
  removeAt,
  removeTagFromResume,
  uniqueTags,
} from "../lib/resumeEdit";
import { useEditorState } from "../state/editorState";

/**
 * Structured editor for data/master_resume.json — validates through the real Pydantic models.
 *
 * Draft state lives in `EditorProvider` so unsaved edits survive a switch to the Tailor tab.
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

  const takenIds = resume ? collectBulletIds(resume) : new Set<string>();

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

      <EducationSection
        entries={resume.education}
        onChange={(education) => setResume({ ...resume, education })}
      />

      <ExperienceSection
        entries={resume.experience}
        vocabList={vocabList}
        takenIds={takenIds}
        experienceIds={collectExperienceIds(resume)}
        onEnsureVocab={ensureVocab}
        onChange={(experience) => setResume({ ...resume, experience })}
      />

      <ProjectsSection
        entries={resume.projects}
        vocabList={vocabList}
        takenIds={takenIds}
        projectIds={collectProjectIds(resume)}
        onEnsureVocab={ensureVocab}
        onChange={(projects) => setResume({ ...resume, projects })}
      />

      <SkillsSection
        groups={resume.skills}
        onChange={(skills) => setResume({ ...resume, skills })}
      />
    </div>
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

function EducationSection({
  entries,
  onChange,
}: {
  entries: Education[];
  onChange: (e: Education[]) => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Education</h2>
        <AddButton
          label="Add education"
          onClick={() => onChange([...entries, blankEducation()])}
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
          <div key={i} className="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <div className="mb-3 flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-ink-muted">
                {edu.school.trim() || `Education #${i + 1}`}
              </p>
              <EntryControls
                index={i}
                total={entries.length}
                hasContent={hasContent}
                label={edu.school}
                onMove={(from, to) => onChange(moveItem(entries, from, to))}
                onRemove={(idx) => onChange(removeAt(entries, idx))}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField
                label="School"
                value={edu.school}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...edu, school: v };
                  onChange(next);
                }}
              />
              <TextField
                label="Location"
                value={edu.location ?? ""}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...edu, location: v };
                  onChange(next);
                }}
              />
              <TextField
                label="Degree"
                value={edu.degree}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...edu, degree: v };
                  onChange(next);
                }}
              />
              <TextField
                label="Dates"
                value={edu.dates}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...edu, dates: v };
                  onChange(next);
                }}
              />
              <div className="sm:col-span-2">
                <TextField
                  label="GPA"
                  value={edu.gpa ?? ""}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...edu, gpa: v };
                    onChange(next);
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
                  onChange(next);
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
                    next[i] = {
                      ...edu,
                      details: [...(edu.details ?? []), ""],
                    };
                    onChange(next);
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
                      onChange(next);
                    }}
                    className="w-full rounded-md border border-line bg-paper/40 px-2 py-1.5 text-sm outline-none focus:border-accent"
                  />
                  <button
                    type="button"
                    title="Remove detail"
                    onClick={() => {
                      const details = (edu.details ?? []).filter((_, j) => j !== di);
                      const next = [...entries];
                      next[i] = { ...edu, details };
                      onChange(next);
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
    </section>
  );
}

function ExperienceSection({
  entries,
  vocabList,
  takenIds,
  experienceIds,
  onEnsureVocab,
  onChange,
}: {
  entries: Experience[];
  vocabList: string[];
  takenIds: Set<string>;
  experienceIds: Set<string>;
  onEnsureVocab: (token: string) => void;
  onChange: (e: Experience[]) => void;
}) {
  function addEntry() {
    const id = nextExperienceId("new role", experienceIds);
    onChange([...entries, blankExperience(id)]);
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Experience</h2>
        <AddButton label="Add experience" onClick={addEntry} />
      </div>
      {entries.map((job, i) => {
        const hasContent =
          Boolean(job.company.trim() || job.title.trim() || job.bullets.length);
        return (
          <div key={i} className="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <div className="mb-3 flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-ink-muted">
                {job.company.trim() || `Experience #${i + 1}`}
              </p>
              <EntryControls
                index={i}
                total={entries.length}
                hasContent={hasContent}
                label={job.company}
                onMove={(from, to) => onChange(moveItem(entries, from, to))}
                onRemove={(idx) => onChange(removeAt(entries, idx))}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField
                label="Company"
                value={job.company}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...job, company: v };
                  onChange(next);
                }}
              />
              <TextField
                label="Title"
                value={job.title}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...job, title: v };
                  onChange(next);
                }}
              />
              <div className="grid grid-cols-2 gap-3">
                <TextField
                  label="Start (YYYY-MM)"
                  value={job.start}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...job, start: v };
                    onChange(next);
                  }}
                />
                <TextField
                  label="End"
                  value={job.end}
                  onChange={(v) => {
                    const next = [...entries];
                    next[i] = { ...job, end: v };
                    onChange(next);
                  }}
                />
              </div>
              <TextField
                label="Location"
                value={job.location ?? ""}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...job, location: v };
                  onChange(next);
                }}
              />
            </div>
            <BulletList
              bullets={job.bullets}
              vocabList={vocabList}
              takenIds={takenIds}
              entryName={job.company}
              onEnsureVocab={onEnsureVocab}
              onChange={(bullets) => {
                const next = [...entries];
                next[i] = { ...job, bullets };
                onChange(next);
              }}
            />
          </div>
        );
      })}
    </section>
  );
}

function ProjectsSection({
  entries,
  vocabList,
  takenIds,
  projectIds,
  onEnsureVocab,
  onChange,
}: {
  entries: Project[];
  vocabList: string[];
  takenIds: Set<string>;
  projectIds: Set<string>;
  onEnsureVocab: (token: string) => void;
  onChange: (e: Project[]) => void;
}) {
  function addEntry() {
    const id = nextProjectId("new project", projectIds);
    onChange([...entries, blankProject(id)]);
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Projects</h2>
        <AddButton label="Add project" onClick={addEntry} />
      </div>
      {entries.map((proj, i) => {
        const hasContent =
          Boolean(proj.name.trim() || proj.url?.trim() || proj.bullets.length);
        const link = proj.link ?? "";
        const url = proj.url ?? "";
        const linkWithoutUrl = Boolean(link.trim()) && !url.trim();
        const urlLooksOdd = Boolean(url.trim()) && !looksLikeHttpUrl(url);

        return (
          <div key={i} className="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <div className="mb-3 flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-medium text-ink-muted">
                  {proj.name.trim() || `Project #${i + 1}`}
                </p>
                <code className="text-xs text-ink-muted">{proj.id}</code>
              </div>
              <EntryControls
                index={i}
                total={entries.length}
                hasContent={hasContent}
                label={proj.name}
                onMove={(from, to) => onChange(moveItem(entries, from, to))}
                onRemove={(idx) => onChange(removeAt(entries, idx))}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField
                label="Name"
                value={proj.name}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...proj, name: v };
                  onChange(next);
                }}
              />
              <TextField
                label="Date"
                value={proj.date ?? ""}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...proj, date: v };
                  onChange(next);
                }}
              />
              <div className="sm:col-span-2">
                <ChipListField
                  label="Tech"
                  items={proj.tech ?? []}
                  onChange={(tech) => {
                    const next = [...entries];
                    next[i] = { ...proj, tech };
                    onChange(next);
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
                  onChange(next);
                }}
              />
              <TextField
                label="GitHub URL"
                value={url}
                onChange={(v) => {
                  const next = [...entries];
                  const nextLink =
                    v.trim() && !link.trim() ? "Github" : proj.link;
                  next[i] = { ...proj, url: v, link: nextLink };
                  onChange(next);
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
              takenIds={takenIds}
              entryName={proj.name}
              onEnsureVocab={onEnsureVocab}
              onChange={(bullets) => {
                const next = [...entries];
                next[i] = { ...proj, bullets };
                onChange(next);
              }}
            />
          </div>
        );
      })}
    </section>
  );
}

function SkillsSection({
  groups,
  onChange,
}: {
  groups: SkillGroup[];
  onChange: (g: SkillGroup[]) => void;
}) {
  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Skills</h2>
        <AddButton
          label="Add skill group"
          onClick={() => onChange([...groups, blankSkillGroup()])}
        />
      </div>
      <div className="mt-3 space-y-4">
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
                      onChange(next);
                    }}
                  />
                </div>
                <EntryControls
                  index={i}
                  total={groups.length}
                  hasContent={hasContent}
                  label={g.label || "skill group"}
                  onMove={(from, to) => onChange(moveItem(groups, from, to))}
                  onRemove={(idx) => onChange(removeAt(groups, idx))}
                />
              </div>
              <ChipListField
                label="Items"
                items={g.items}
                onChange={(items) => {
                  const next = [...groups];
                  next[i] = { ...g, items };
                  onChange(next);
                }}
                placeholder="Add a skill"
              />
            </div>
          );
        })}
      </div>
    </section>
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
    onChange(insertAt(bullets, bullets.length, blankBullet(id)));
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
