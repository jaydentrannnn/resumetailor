/**
 * Pure helpers for growing, shrinking, and reordering master-resume sections.
 *
 * Bullet ids and entry ids must be unique across the whole file (server-side
 * MasterResume._ids_unique checks every entry-kind section together, not per
 * section). Prefixes like `aol` / `aeth` are hand-chosen abbreviations, so we
 * reuse an entry's existing `_bN` prefix when present.
 */

export type Bullet = {
  id: string;
  text: string;
  tags: string[];
  metric?: boolean;
};

export type Experience = {
  id: string;
  company: string;
  title: string;
  location?: string;
  start: string;
  end: string;
  bullets: Bullet[];
};

export type Project = {
  id: string;
  name: string;
  tech?: string[];
  /** Month (`YYYY-MM`) or `Present`; an end equal to the start, or none, prints one date. */
  start?: string;
  end?: string;
  /** Free text printed only when no start/end is set ("Spring 2025"). */
  date?: string;
  link?: string;
  url?: string;
  bullets: Bullet[];
};

export type SkillGroup = {
  label: string;
  items: string[];
  /** Client-only React list key — never sent to the server (see `stripRowKeys`).
   * Unlike a bullet or entry, a skill group has no server-assigned id at all. */
  _key?: string;
};

export type Education = {
  school: string;
  degree: string;
  dates: string;
  location?: string;
  coursework?: string[];
  gpa?: string;
  show_gpa?: boolean;
  details?: string[];
  /** Field of study for application forms; never printed on the resume. */
  major?: string;
  /** Start and (expected) graduation month, `YYYY-MM`, for application forms. Never
   * printed; the server fills them from `dates` on save when empty. */
  start?: string;
  end?: string;
  /** Client-only React list key — never sent to the server (see `stripRowKeys`).
   * Unlike a bullet or entry, an education row has no server-assigned id at all. */
  _key?: string;
};

/** One line in a plain bulleted section — a certification, an award, a language. */
export type ListItem = { id: string; text: string; tags?: string[]; _key?: string };

export type SectionKind = "experience" | "project" | "list" | "education" | "skills";

export type ExperienceSection = {
  id: string;
  title: string;
  kind: "experience";
  entries: Experience[];
};
export type ProjectSection = {
  id: string;
  title: string;
  kind: "project";
  entries: Project[];
};
export type ListSection = {
  id: string;
  title: string;
  kind: "list";
  entries: ListItem[];
};
export type EducationSection = {
  id: string;
  title: string;
  kind: "education";
  entries: Education[];
};
export type SkillsSection = {
  id: string;
  title: string;
  kind: "skills";
  entries: SkillGroup[];
};

export type Section =
  ExperienceSection | ProjectSection | ListSection | EducationSection | SkillsSection;

export type MasterResume = {
  _comment?: string | null;
  contact: {
    name: string;
    email: string;
    phone?: string;
    location?: string;
    linkedin?: string;
    github?: string;
    links?: string[];
  };
  sections: Section[];
  tag_vocabulary?: string[];
};

/** Human-facing label for a section kind, e.g. in the "Add section" picker. */
export const SECTION_KIND_LABELS: Record<SectionKind, string> = {
  experience: "Experience-like",
  project: "Project-like",
  list: "Simple list",
  education: "Education",
  skills: "Skills",
};

/** Default title given to a freshly created section of one kind. */
export const DEFAULT_SECTION_TITLES: Record<SectionKind, string> = {
  experience: "Experience",
  project: "Projects",
  list: "Additional Information",
  education: "Education",
  skills: "Skills",
};

/** "Add section" choices: familiar resume headings mapped onto the five kinds. */
export const SECTION_PRESETS: { title: string; kind: SectionKind; hint: string }[] = [
  { title: "Experience", kind: "experience", hint: "Jobs and internships" },
  { title: "Research", kind: "experience", hint: "Labs and research assistant roles" },
  { title: "Leadership", kind: "experience", hint: "Club officer, team lead" },
  { title: "Activities", kind: "experience", hint: "Clubs, competitions, teams" },
  { title: "Volunteering", kind: "experience", hint: "Community service" },
  { title: "Projects", kind: "project", hint: "Class, personal or hackathon projects" },
  { title: "Education", kind: "education", hint: "Schools and degrees" },
  { title: "Skills", kind: "skills", hint: "Grouped skill lists" },
  { title: "Certifications", kind: "list", hint: "One line each" },
  { title: "Awards", kind: "list", hint: "Honors and scholarships" },
  { title: "Publications", kind: "list", hint: "Papers and posters" },
  { title: "Languages", kind: "list", hint: "Spoken languages" },
];

/** Insert `item` at `index`, shifting later elements right. */
export function insertAt<T>(list: T[], index: number, item: T): T[] {
  const next = [...list];
  next.splice(index, 0, item);
  return next;
}

/** Remove the element at `index`. */
export function removeAt<T>(list: T[], index: number): T[] {
  return list.filter((_, i) => i !== index);
}

/** Move the element at `from` to `to` (clamped). */
export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || from >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  const clamped = Math.max(0, Math.min(to, next.length));
  next.splice(clamped, 0, item);
  return next;
}

/** Sections of one kind, in resume order. */
export function sectionsOfKind<K extends SectionKind>(
  resume: MasterResume,
  kind: K,
): Extract<Section, { kind: K }>[] {
  return resume.sections.filter((s): s is Extract<Section, { kind: K }> => s.kind === kind);
}

/** Every experience entry, flattened across all experience-kind sections. */
export function flatExperience(resume: MasterResume): Experience[] {
  return sectionsOfKind(resume, "experience").flatMap((s) => s.entries);
}

/** Every project entry, flattened across all project-kind sections. */
export function flatProjects(resume: MasterResume): Project[] {
  return sectionsOfKind(resume, "project").flatMap((s) => s.entries);
}

/** Every education entry, flattened across all education-kind sections. */
export function flatEducation(resume: MasterResume): Education[] {
  return sectionsOfKind(resume, "education").flatMap((s) => s.entries);
}

/** Every skill group, flattened across all skills-kind sections. */
export function flatSkills(resume: MasterResume): SkillGroup[] {
  return sectionsOfKind(resume, "skills").flatMap((s) => s.entries);
}

/** Every bullet id across every experience/project section. */
export function collectBulletIds(resume: MasterResume): Set<string> {
  const ids = new Set<string>();
  for (const job of flatExperience(resume)) {
    for (const b of job.bullets) ids.add(b.id);
  }
  for (const proj of flatProjects(resume)) {
    for (const b of proj.bullets) ids.add(b.id);
  }
  return ids;
}

/** Every experience/project entry id, across every section of either kind — one flat
 * namespace, matching `data.MasterResume._ids_unique` server-side. */
export function collectEntryIds(resume: MasterResume): Set<string> {
  const ids = new Set<string>();
  for (const job of flatExperience(resume)) if (job.id) ids.add(job.id);
  for (const proj of flatProjects(resume)) ids.add(proj.id);
  return ids;
}

/** Every section id currently in use. */
export function collectSectionIds(resume: MasterResume): Set<string> {
  return new Set(resume.sections.map((s) => s.id));
}

/**
 * Prefer the existing `_bN` prefix on the entry's first bullet; otherwise slug
 * the fallback name. Existing prefixes (`aol`, `aeth`, …) are not name-derivable.
 */
export function entryPrefix(bullets: Bullet[], fallbackName: string): string {
  const first = bullets[0]?.id;
  if (first) {
    const m = first.match(/^(.*)_b\d+$/);
    if (m?.[1]) return m[1];
  }
  return slugify(fallbackName) || "entry";
}

/** Next free `<prefix>_bN` against the global taken set. */
export function nextBulletId(prefix: string, taken: Set<string>): string {
  let n = 1;
  while (taken.has(`${prefix}_b${n}`)) n += 1;
  return `${prefix}_b${n}`;
}

/** Next free entry id for a new row of the given kind, against the shared entry-id
 * namespace. Projects keep their historical `proj_<slug>` style; experience-kind rows
 * (including non-default sections like "Leadership") use the bare slug. */
export function nextEntryId(
  kind: "experience" | "project",
  name: string,
  taken: Set<string>,
): string {
  const base = kind === "project" ? `proj_${slugify(name) || "project"}` : slugify(name) || "role";
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

/** Next free id for a new section, against the section-id namespace. */
export function nextSectionId(title: string, kind: SectionKind, taken: Set<string>): string {
  const base = slugify(title) || kind;
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

/** Empty bullet with a pre-allocated unique id. */
export function blankBullet(id: string): Bullet {
  return { id, text: "", tags: [], metric: false };
}

/** Empty experience row ready for the editor. */
export function blankExperience(id: string): Experience {
  return { id, company: "", title: "", location: "", start: "", end: "", bullets: [] };
}

/**
 * Empty project row. `link` defaults to "Github" so a typed URL produces a
 * real hyperlink without a second field fill (render needs both link + url).
 */
export function blankProject(id: string): Project {
  return {
    id,
    name: "",
    tech: [],
    start: "",
    end: "",
    date: "",
    link: "Github",
    url: "",
    bullets: [],
  };
}

/** Empty skill-group row. */
export function blankSkillGroup(): SkillGroup {
  return { _key: makeRowKey(), label: "", items: [] };
}

/** Empty education row. */
export function blankEducation(): Education {
  return {
    _key: makeRowKey(),
    school: "",
    degree: "",
    dates: "",
    location: "",
    coursework: [],
    gpa: "",
    show_gpa: false,
    details: [],
  };
}

/** Small client-side id for React list identity on rows with no server-assigned id
 * (Education, SkillGroup, and section-local ListItem ids). Survives object spreads since it
 * is a real property, which is exactly what makes it a stable React `key` across
 * edits — unlike `key={i}`, which reattaches to the wrong row on move/remove. */
export function makeRowKey(): string {
  return `k_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Backfill `_key` onto every Education/SkillGroup/ListItem entry that lacks one. A resume
 * freshly fetched from the server never has it (the field is client-only); call this
 * once right after any load so `EditorPage`'s row components get stable React keys.
 */
export function withRowKeys(resume: MasterResume): MasterResume {
  return {
    ...resume,
    sections: resume.sections.map((section) => {
      if (section.kind === "education") {
        return {
          ...section,
          entries: section.entries.map((e) => (e._key ? e : { ...e, _key: makeRowKey() })),
        };
      }
      if (section.kind === "skills") {
        return {
          ...section,
          entries: section.entries.map((g) => (g._key ? g : { ...g, _key: makeRowKey() })),
        };
      }
      if (section.kind === "list") {
        return {
          ...section,
          entries: section.entries.map((item) =>
            item._key ? item : { ...item, _key: makeRowKey() },
          ),
        };
      }
      return section;
    }),
  };
}

/**
 * Inverse of `withRowKeys` — strips the client-only `_key` before the resume leaves
 * the browser. The server's Pydantic models reject unknown fields (`extra="forbid"`),
 * so every save/validate call must send this, not the raw editor state.
 */
export function stripRowKeys(resume: MasterResume): MasterResume {
  return {
    ...resume,
    sections: resume.sections.map((section) => {
      if (section.kind === "education") {
        return {
          ...section,
          entries: section.entries.map(({ _key, ...rest }) => rest),
        };
      }
      if (section.kind === "skills") {
        return {
          ...section,
          entries: section.entries.map(({ _key, ...rest }) => rest),
        };
      }
      if (section.kind === "list") {
        return {
          ...section,
          entries: section.entries.map(({ _key, ...rest }) => rest),
        };
      }
      return section;
    }),
  };
}

/** Empty list-item row with a pre-allocated unique id. */
export function blankListItem(id: string): ListItem {
  return { id, text: "", tags: [], _key: makeRowKey() };
}

/** A freshly created, empty section of the given kind. */
export function blankSection(id: string, kind: SectionKind, title?: string): Section {
  const sectionTitle = title ?? DEFAULT_SECTION_TITLES[kind];
  switch (kind) {
    case "experience":
      return { id, title: sectionTitle, kind, entries: [] };
    case "project":
      return { id, title: sectionTitle, kind, entries: [] };
    case "list":
      return { id, title: sectionTitle, kind, entries: [] };
    case "education":
      return { id, title: sectionTitle, kind, entries: [] };
    case "skills":
      return { id, title: sectionTitle, kind, entries: [] };
  }
}

/**
 * Split a comma-separated editor string into trimmed non-empty tokens.
 *
 * Prefer `ChipListField` for new UI; this remains for any leftover draft parsers.
 */
export function parseCommaList(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/**
 * Case-insensitive set: keep first spelling, drop later duplicates.
 * Tags are stored as arrays in JSON but are set-valued — no duplicates.
 */
export function uniqueTags(tags: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of tags) {
    const t = raw.trim();
    if (!t) continue;
    const key = t.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(t);
  }
  return out;
}

/**
 * Add `tag` to the stored vocabulary if missing (case-insensitive).
 * Returns a new sorted list; does not mutate `vocab`.
 */
export function addToVocabulary(vocab: string[], tag: string): string[] {
  const cleaned = tag.trim();
  if (!cleaned) return vocab;
  return uniqueTags([...vocab, cleaned]).sort((a, b) =>
    a.toLowerCase().localeCompare(b.toLowerCase()),
  );
}

/**
 * Remove `tag` from the vocabulary and strip it from every bullet's tags, in every
 * experience/project section. Returns a shallow-copied resume; does not mutate the input.
 */
export function removeTagFromResume(resume: MasterResume, tag: string): MasterResume {
  const lower = tag.toLowerCase();
  const strip = (tags: string[]) => tags.filter((t) => t.toLowerCase() !== lower);

  return {
    ...resume,
    tag_vocabulary: (resume.tag_vocabulary ?? []).filter((t) => t.toLowerCase() !== lower),
    sections: resume.sections.map((section) => {
      if (section.kind === "experience") {
        return {
          ...section,
          entries: section.entries.map((job) => ({
            ...job,
            bullets: job.bullets.map((b) => ({ ...b, tags: strip(b.tags) })),
          })),
        };
      }
      if (section.kind === "project") {
        return {
          ...section,
          entries: section.entries.map((proj) => ({
            ...proj,
            bullets: proj.bullets.map((b) => ({ ...b, tags: strip(b.tags) })),
          })),
        };
      }
      return section;
    }),
  };
}

/** How many bullets currently carry `tag` (case-insensitive), across every section. */
export function countTagUsage(resume: MasterResume, tag: string): number {
  const lower = tag.toLowerCase();
  let n = 0;
  for (const job of flatExperience(resume)) {
    for (const b of job.bullets) {
      if (b.tags.some((t) => t.toLowerCase() === lower)) n += 1;
    }
  }
  for (const proj of flatProjects(resume)) {
    for (const b of proj.bullets) {
      if (b.tags.some((t) => t.toLowerCase() === lower)) n += 1;
    }
  }
  return n;
}

/**
 * Client-side completeness messages that name the offending row.
 * Server validation remains authoritative; this only blocks the obvious blanks
 * a new row creates before the Pydantic path errors are hard to map back.
 */
export function completenessErrors(resume: MasterResume): string[] {
  const errors: string[] = [];

  for (const section of resume.sections) {
    if (section.kind === "education") {
      section.entries.forEach((edu, i) => {
        const label = edu.school.trim() || `${section.title} #${i + 1}`;
        if (!edu.school.trim()) errors.push(`${label}: school is required`);
        if (!edu.degree.trim()) errors.push(`${label}: degree is required`);
        if (!edu.dates.trim()) errors.push(`${label}: dates are required`);
      });
    } else if (section.kind === "experience") {
      section.entries.forEach((job, i) => {
        const label = job.company.trim() || `${section.title} #${i + 1}`;
        if (!job.company.trim()) errors.push(`${label}: company is required`);
        if (!job.title.trim()) errors.push(`${label}: title is required`);
        if (!job.start.trim()) errors.push(`${label}: start date is required`);
        if (!job.end.trim()) errors.push(`${label}: end date is required`);
        job.bullets.forEach((b, bi) => {
          const bl = `${label} — bullet ${bi + 1} (${b.id})`;
          if (!b.text.trim()) errors.push(`${bl}: text is empty`);
          if (b.tags.length === 0) errors.push(`${bl}: needs at least one tag`);
        });
      });
    } else if (section.kind === "project") {
      section.entries.forEach((proj, i) => {
        const label = proj.name.trim() || `${section.title} #${i + 1}`;
        if (!proj.name.trim()) errors.push(`${label}: name is required`);
        proj.bullets.forEach((b, bi) => {
          const bl = `${label} — bullet ${bi + 1} (${b.id})`;
          if (!b.text.trim()) errors.push(`${bl}: text is empty`);
          if (b.tags.length === 0) errors.push(`${bl}: needs at least one tag`);
        });
      });
    } else if (section.kind === "list") {
      section.entries.forEach((item, i) => {
        const label = `${section.title} #${i + 1}`;
        if (!item.text.trim()) errors.push(`${label}: text is empty`);
      });
    } else if (section.kind === "skills") {
      section.entries.forEach((g, i) => {
        const label = g.label.trim() || `${section.title} #${i + 1}`;
        if (!g.label.trim()) errors.push(`${label}: label is required`);
        if (g.items.length === 0) errors.push(`${label}: needs at least one item`);
      });
    }
  }

  return errors;
}

/** True when a URL looks like an absolute http(s) link. */
export function looksLikeHttpUrl(url: string): boolean {
  return /^https?:\/\//i.test(url.trim());
}

function slugify(name: string): string {
  /** Lowercase alphanumerics joined by underscores; empty when nothing usable. */
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}
