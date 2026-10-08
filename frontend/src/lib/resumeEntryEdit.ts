import type {
  Education,
  Experience,
  ListItem,
  MasterResume,
  Project,
  SkillGroup,
} from "./resumeEdit";

export type ResumeEntry = Experience | Project | Education | SkillGroup | ListItem;

/** List ids can repeat across sections; their client keys keep UI identity unique. */
export function resumeEntryKey(entry: ResumeEntry): string {
  if ("_key" in entry && entry._key) return entry._key;
  if ("id" in entry) return entry.id;
  throw new Error("Resume entry is missing its editor key");
}

/** Transfer an unchanged entry in one draft update, only between matching kinds. */
export function moveEntryToSection(
  resume: MasterResume,
  sourceId: string,
  entryKey: string,
  destinationId: string,
): MasterResume {
  const source = resume.sections.find((section) => section.id === sourceId);
  const destination = resume.sections.find((section) => section.id === destinationId);
  if (!source || !destination || source === destination || source.kind !== destination.kind) {
    return resume;
  }
  const entry = source.entries.find((item) => resumeEntryKey(item) === entryKey);
  if (!entry) return resume;
  return {
    ...resume,
    sections: resume.sections.map((section) => {
      if (section === source) {
        return {
          ...section,
          entries: section.entries.filter((item) => item !== entry),
        } as typeof section;
      }
      if (section === destination) {
        // The kind equality above guarantees that the transferred entry has this schema.
        return { ...section, entries: [...section.entries, entry] } as typeof section;
      }
      return section;
    }),
  };
}
