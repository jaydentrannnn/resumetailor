import { useEffect, useMemo, useState } from "react";
import {
  type AppConfig,
  fetchConfig,
  fetchMasterResume,
  saveMasterResume,
  validateMasterResume,
} from "../api";
import { AddButton, EntryControls } from "../components/ListControls";
import {
  type Bullet,
  type Experience,
  type MasterResume,
  type Project,
  type SkillGroup,
  blankBullet,
  blankExperience,
  blankProject,
  blankSkillGroup,
  collectBulletIds,
  collectProjectIds,
  completenessErrors,
  entryPrefix,
  insertAt,
  looksLikeHttpUrl,
  moveItem,
  nextBulletId,
  nextProjectId,
  removeAt,
} from "../lib/resumeEdit";

/**
 * Structured editor for data/master_resume.json — validates through the real Pydantic models.
 */
export function EditorPage() {
  const [resume, setResume] = useState<MasterResume | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([fetchMasterResume(), fetchConfig()])
      .then(([raw, cfg]) => {
        setResume(raw as MasterResume);
        setConfig(cfg);
      })
      .catch((err: Error) => setErrors([err.message]));
  }, []);

  const tagVocab = useMemo(
    () => new Set(config?.tag_vocabulary ?? []),
    [config],
  );

  const takenIds = useMemo(
    () => (resume ? collectBulletIds(resume) : new Set<string>()),
    [resume],
  );

  async function onValidate() {
    if (!resume) return;
    setBusy(true);
    setMessage(null);
    try {
      const local = completenessErrors(resume);
      if (local.length) {
        setErrors(local);
        setBusy(false);
        return;
      }
      const result = await validateMasterResume(resume as unknown as Record<string, unknown>);
      setErrors(result.errors);
      if (result.ok && result.summary) {
        setMessage(
          `Valid — ${result.summary.bullets} bullets, ${result.summary.tags} tags`,
        );
      }
    } catch (err) {
      setErrors([err instanceof Error ? err.message : String(err)]);
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    if (!resume) return;
    setBusy(true);
    setMessage(null);
    try {
      const local = completenessErrors(resume);
      if (local.length) {
        setErrors(local);
        setBusy(false);
        return;
      }
      const result = await saveMasterResume(resume as unknown as Record<string, unknown>);
      setErrors(result.errors);
      if (result.ok && result.summary) {
        setMessage(
          `Saved — ${result.summary.name}: ${result.summary.bullets} bullets (previous file backed up)`,
        );
        // Reload so tags come back canonicalised the way the server stored them.
        const fresh = (await fetchMasterResume()) as MasterResume;
        setResume(fresh);
        const cfg = await fetchConfig();
        setConfig(cfg);
      }
    } catch (err) {
      setErrors([err instanceof Error ? err.message : String(err)]);
    } finally {
      setBusy(false);
    }
  }

  if (!resume) {
    return (
      <p className="text-sm text-ink-muted">
        {errors.length ? errors.join("; ") : "Loading master resume…"}
      </p>
    );
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
        </div>
      </section>

      <ExperienceSection
        entries={resume.experience}
        tagVocab={tagVocab}
        takenIds={takenIds}
        onChange={(experience) => setResume({ ...resume, experience })}
      />

      <ProjectsSection
        entries={resume.projects}
        tagVocab={tagVocab}
        takenIds={takenIds}
        projectIds={collectProjectIds(resume)}
        onChange={(projects) => setResume({ ...resume, projects })}
      />

      <SkillsSection
        groups={resume.skills}
        onChange={(skills) => setResume({ ...resume, skills })}
      />
    </div>
  );
}

function ExperienceSection({
  entries,
  tagVocab,
  takenIds,
  onChange,
}: {
  entries: Experience[];
  tagVocab: Set<string>;
  takenIds: Set<string>;
  onChange: (e: Experience[]) => void;
}) {
  function addEntry() {
    onChange([...entries, blankExperience()]);
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
              <TextField
                label="Location"
                value={job.location ?? ""}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = { ...job, location: v };
                  onChange(next);
                }}
              />
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
            <BulletList
              bullets={job.bullets}
              tagVocab={tagVocab}
              takenIds={takenIds}
              entryName={job.company}
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
  tagVocab,
  takenIds,
  projectIds,
  onChange,
}: {
  entries: Project[];
  tagVocab: Set<string>;
  takenIds: Set<string>;
  projectIds: Set<string>;
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
                label="Tech (comma-separated)"
                value={(proj.tech ?? []).join(", ")}
                onChange={(v) => {
                  const next = [...entries];
                  next[i] = {
                    ...proj,
                    tech: v
                      .split(",")
                      .map((t) => t.trim())
                      .filter(Boolean),
                  };
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
                  // Auto-fill the resume label when typing a URL into an empty label.
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
              tagVocab={tagVocab}
              takenIds={takenIds}
              entryName={proj.name}
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
      <div className="mt-3 space-y-3">
        {groups.map((g, i) => {
          const hasContent = Boolean(g.label.trim() || g.items.length);
          return (
            <div key={i} className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <div className="grid flex-1 gap-2 sm:grid-cols-[10rem_1fr]">
                <TextField
                  label="Label"
                  value={g.label}
                  onChange={(v) => {
                    const next = [...groups];
                    next[i] = { ...g, label: v };
                    onChange(next);
                  }}
                />
                <TextField
                  label="Items (comma-separated)"
                  value={g.items.join(", ")}
                  onChange={(v) => {
                    const next = [...groups];
                    next[i] = {
                      ...g,
                      items: v
                        .split(",")
                        .map((t) => t.trim())
                        .filter(Boolean),
                    };
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
          );
        })}
      </div>
    </section>
  );
}

function BulletList({
  bullets,
  tagVocab,
  takenIds,
  entryName,
  onChange,
}: {
  bullets: Bullet[];
  tagVocab: Set<string>;
  takenIds: Set<string>;
  entryName: string;
  onChange: (b: Bullet[]) => void;
}) {
  function addBullet() {
    const prefix = entryPrefix(bullets, entryName);
    const id = nextBulletId(prefix, takenIds);
    onChange(insertAt(bullets, bullets.length, blankBullet(id)));
  }

  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-ink-muted">Bullets</h3>
        <AddButton label="Add bullet" onClick={addBullet} />
      </div>
      {bullets.map((b, i) => {
        const missing = suggestMissingTags(b.text, b.tags, tagVocab);
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
            <TextField
              label="Tags (comma-separated)"
              value={b.tags.join(", ")}
              onChange={(v) => {
                const next = [...bullets];
                next[i] = {
                  ...b,
                  tags: v
                    .split(",")
                    .map((t) => t.trim())
                    .filter(Boolean),
                };
                onChange(next);
              }}
            />
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
  vocab: Set<string>,
): string[] {
  /**
   * Flag vocabulary words that appear in the bullet text but not its tags.
   * Tags are the fabrication guard's whitelist — a miss here is a future false positive.
   */
  const have = new Set(tags.map((t) => t.toLowerCase()));
  const lower = text.toLowerCase();
  const hits: string[] = [];
  for (const tag of vocab) {
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
