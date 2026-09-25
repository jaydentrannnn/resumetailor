/**
 * Plain-language names for the app's internal terms, with a one-line explanation for
 * `InlineHelp`. Labels and tooltips use these so a first-time user never meets
 * "widows" or "semantic weight".
 */
export interface GlossaryEntry {
  label: string;
  help: string;
}

export const GLOSSARY = {
  mustHaves: {
    label: "Required skills covered",
    help: "How many of the posting's must-have skills your tailored resume shows.",
  },
  widows: {
    label: "Short last lines",
    help: "Bullets whose last line holds only a word or two. They waste a line of space.",
  },
  verbRepeats: {
    label: "Repeated opening verbs",
    help: "Bullets in one entry that start with the same verb, which reads as repetitive.",
  },
  coverage: {
    label: "Skill match",
    help: "Share of the posting's skills that appear in your resume.",
  },
  calibrated: {
    label: "Page fit tuned for your template",
    help: "ResumeTailor measured how much text fits on a page of your template, so it can fill the page without overflowing.",
  },
  semantic: {
    label: "Smart ranking",
    help: "Uses the AI to judge how relevant each bullet is, on top of exact keyword matches.",
  },
  effort: {
    label: "Model thinking effort",
    help: "Higher effort can give better wording but is slower and costs more on paid models.",
  },
  bypassCache: {
    label: "Force fresh results",
    help: "Ignore saved results for this posting and ask the model again.",
  },
  screenedOut: {
    label: "Filtered out",
    help: "Postings your filters rejected, for example ones requiring citizenship or a graduate degree.",
  },
  prepare: {
    label: "Tailor files",
    help: "Make the tailored resume (and cover letter) for the selected postings.",
  },
  packet: {
    label: "Application kit",
    help: "Everything a form fill uses: your tailored files and your saved answers.",
  },
  fabrication: {
    label: "Unsupported claim",
    help: "Wording that is not backed by your master resume. ResumeTailor never adds facts you did not write.",
  },
  merge: {
    label: "Combine similar bullets",
    help: "When the page overflows, allow two closely related bullets to be merged into one.",
  },
  fillTarget: {
    label: "Page fill goal",
    help: "How full the page should be before ResumeTailor stops adding bullets back.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;

export function term(key: GlossaryKey): string {
  return GLOSSARY[key].label;
}
