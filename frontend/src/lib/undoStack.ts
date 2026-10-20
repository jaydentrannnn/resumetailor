import type { MasterResume } from "./resumeEdit";

/**
 * Undo / redo for the resume editor's structural edits: whole-resume snapshots, newest
 * last. Text typed into a field is the field's own undo (Ctrl+Z while typing); this
 * stack holds adding, removing, moving and reordering sections, entries and bullets.
 */
export type UndoStep<T> = { snapshot: T; label: string };
export type UndoStack<T> = { past: UndoStep<T>[]; future: UndoStep<T>[] };

export const UNDO_LIMIT = 50;

export function emptyStack<T>(): UndoStack<T> {
  return { past: [], future: [] };
}

/** Remember `snapshot` (the state before a change); a new change drops the redo steps. */
export function record<T>(stack: UndoStack<T>, snapshot: T, label: string): UndoStack<T> {
  return { past: [...stack.past, { snapshot, label }].slice(-UNDO_LIMIT), future: [] };
}

/** Step back: the snapshot to show, with `current` kept for Redo. Null when empty. */
export function undo<T>(
  stack: UndoStack<T>,
  current: T,
): { stack: UndoStack<T>; step: UndoStep<T> } | null {
  const step = stack.past.at(-1);
  if (!step) return null;
  return {
    step,
    stack: {
      past: stack.past.slice(0, -1),
      future: [...stack.future, { snapshot: current, label: step.label }],
    },
  };
}

/** Step forward again after an undo. Null when there is nothing to redo. */
export function redo<T>(
  stack: UndoStack<T>,
  current: T,
): { stack: UndoStack<T>; step: UndoStep<T> } | null {
  const step = stack.future.at(-1);
  if (!step) return null;
  return {
    step,
    stack: {
      past: [...stack.past, { snapshot: current, label: step.label }],
      future: stack.future.slice(0, -1),
    },
  };
}

type Identified = { id?: string; _key?: string; bullets?: { id: string }[] };

/**
 * The resume's shape: section, entry and bullet identities in order. It changes when
 * something is added, removed or moved, and not when text is typed.
 */
export function structureKey(resume: MasterResume): string {
  return resume.sections
    .map((section) => {
      const entries = (section.entries as Identified[]).map((entry, i) => {
        const bullets = entry.bullets?.map((bullet) => bullet.id).join(",") ?? "";
        return `${entry.id ?? entry._key ?? i}[${bullets}]`;
      });
      return `${section.id}{${entries.join(";")}}`;
    })
    .join("|");
}

/** A name for a structural change the editor did not label itself. */
export function describeChange(before: MasterResume, after: MasterResume): string {
  const count = (resume: MasterResume) => {
    const entries = resume.sections.flatMap((s) => s.entries as Identified[]);
    return {
      sections: resume.sections.length,
      entries: entries.length,
      bullets: entries.reduce((n, entry) => n + (entry.bullets?.length ?? 0), 0),
    };
  };
  const a = count(before);
  const b = count(after);
  if (b.sections > a.sections) return "Added a section";
  if (b.entries > a.entries) return "Added an entry";
  if (b.bullets > a.bullets) return "Added a bullet";
  if (b.sections < a.sections || b.entries < a.entries || b.bullets < a.bullets)
    return "Removed an item";
  return "Moved an item";
}

// A list row's id can repeat across sections; its client-only `_key` cannot.
const entryKey = (entry: Identified): string | undefined => entry._key ?? entry.id;

/**
 * Undo / redo's result: `structure`'s sections, entries and bullets in its order, each
 * one's content taken from `live` wherever it still exists there (matched by id, across
 * sections, so a moved entry keeps its edits). A text edit made after the structural
 * change survives undoing it; what the change removed comes back from `structure`.
 */
export function restoreStructure(structure: MasterResume, live: MasterResume): MasterResume {
  const sections = new Map(live.sections.map((section) => [section.id, section]));
  const entries = new Map<string, Identified>();
  const bullets = new Map<string, { id: string }>();
  for (const section of live.sections)
    for (const entry of section.entries as Identified[]) {
      const key = entryKey(entry);
      if (key) entries.set(key, entry);
      for (const bullet of entry.bullets ?? []) bullets.set(bullet.id, bullet);
    }
  const restoreEntry = (entry: Identified): Identified => {
    const key = entryKey(entry);
    const current = (key && entries.get(key)) || entry;
    if (!entry.bullets) return current;
    return { ...current, bullets: entry.bullets.map((b) => bullets.get(b.id) ?? b) };
  };
  return {
    ...live,
    sections: structure.sections.map((section) => ({
      ...(sections.get(section.id) ?? section),
      entries: (section.entries as Identified[]).map(restoreEntry),
    })) as MasterResume["sections"],
  };
}
