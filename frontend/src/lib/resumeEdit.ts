/**
 * Pure helpers for growing, shrinking, and reordering master-resume lists.
 *
 * Bullet ids must be unique across experience and projects (server-side
 * MasterResume._ids_unique). Prefixes like `aol` / `aeth` are hand-chosen
 * abbreviations, so we reuse an entry's existing `_bN` prefix when present.
 */

export type Bullet = {
  id: string;
  text: string;
  tags: string[];
  metric?: boolean;
};

export type Experience = {
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
  date?: string;
  link?: string;
  url?: string;
  bullets: Bullet[];
};

export type SkillGroup = { label: string; items: string[] };

export type MasterResume = {
  _comment?: string | null;
  contact: {
    name: string;
    email: string;
    phone?: string;
    location?: string;
    links?: string[];
  };
  education: unknown[];
  summary_variants?: unknown[];
  experience: Experience[];
  projects: Project[];
  skills: SkillGroup[];
};

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

/** Every bullet id across experience and projects. */
export function collectBulletIds(resume: MasterResume): Set<string> {
  const ids = new Set<string>();
  for (const job of resume.experience) {
    for (const b of job.bullets) ids.add(b.id);
  }
  for (const proj of resume.projects) {
    for (const b of proj.bullets) ids.add(b.id);
  }
  return ids;
}

/** Every project entry id (for nextProjectId dedupe). */
export function collectProjectIds(resume: MasterResume): Set<string> {
  return new Set(resume.projects.map((p) => p.id));
}

/**
 * Prefer the existing `_bN` prefix on the entry's first bullet; otherwise slug
 * the fallback name. Existing prefixes (`aol`, `aeth`, …) are not name-derivable.
 */
export function entryPrefix(
  bullets: Bullet[],
  fallbackName: string,
): string {
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

/** Next free `proj_<slug>` matching existing project id style. */
export function nextProjectId(name: string, taken: Set<string>): string {
  const base = `proj_${slugify(name) || "project"}`;
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
export function blankExperience(): Experience {
  return {
    company: "",
    title: "",
    location: "",
    start: "",
    end: "",
    bullets: [],
  };
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
    date: "",
    link: "Github",
    url: "",
    bullets: [],
  };
}

/** Empty skill-group row. */
export function blankSkillGroup(): SkillGroup {
  return { label: "", items: [] };
}

/**
 * Client-side completeness messages that name the offending row.
 * Server validation remains authoritative; this only blocks the obvious blanks
 * a new row creates before the Pydantic path errors are hard to map back.
 */
export function completenessErrors(resume: MasterResume): string[] {
  const errors: string[] = [];

  resume.experience.forEach((job, i) => {
    const label = job.company.trim() || `Experience #${i + 1}`;
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

  resume.projects.forEach((proj, i) => {
    const label = proj.name.trim() || `Project #${i + 1}`;
    if (!proj.name.trim()) errors.push(`${label}: name is required`);
    proj.bullets.forEach((b, bi) => {
      const bl = `${label} — bullet ${bi + 1} (${b.id})`;
      if (!b.text.trim()) errors.push(`${bl}: text is empty`);
      if (b.tags.length === 0) errors.push(`${bl}: needs at least one tag`);
    });
  });

  resume.skills.forEach((g, i) => {
    const label = g.label.trim() || `Skill group #${i + 1}`;
    if (!g.label.trim()) errors.push(`${label}: label is required`);
    if (g.items.length === 0) errors.push(`${label}: needs at least one item`);
  });

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
