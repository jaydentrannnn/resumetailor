import { MONTH_NAMES } from "./dates";
import type { MasterResume, Section } from "./resumeEdit";
import type { ResumeEntry } from "./resumeEntryEdit";

const TOKEN =
  /\b(?:present|current|now|ongoing|today)\b|\b\d{4}-\d{1,2}(?:-\d{1,2})?(?!\d)|\b\d{1,2}[/.]\d{4}\b|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|spring|summer|fall|autumn|winter)\.?,?\s+'?\d{2,4}\b|\b\d{4}\b/gi;
const SEASONS: Record<string, [number, number]> = {
  spring: [1, 5],
  summer: [6, 8],
  fall: [9, 12],
  autumn: [9, 12],
  winter: [1, 3],
};

function month(token: string, end: boolean): number {
  if (/^(present|current|now|ongoing|today)$/i.test(token)) return 999999;
  let year = 0,
    mm = 12;
  const iso = /^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$/.exec(token);
  const numeric = /^(\d{1,2})[/.](\d{4})$/.exec(token);
  const named = /^([a-z]+)\.?,?\s+'?(\d{2,4})$/i.exec(token);
  if (iso) {
    year = Number(iso[1]);
    mm = iso[2] ? Number(iso[2]) : 12;
    if (iso[3] && (Number(iso[3]) < 1 || Number(iso[3]) > new Date(year, mm, 0).getDate()))
      return 0;
  } else if (numeric) {
    year = Number(numeric[2]);
    mm = Number(numeric[1]);
  } else if (named) {
    year = Number(named[2]) + (named[2].length === 2 ? 2000 : 0);
    const word = named[1].toLowerCase();
    mm =
      SEASONS[word]?.[end ? 1 : 0] ??
      MONTH_NAMES.findIndex((name) => name.toLowerCase().startsWith(word.slice(0, 3))) + 1;
  }
  return year >= 1950 && year <= 2100 && mm >= 1 && mm <= 12 ? year * 12 + mm : 0;
}

function span(text: string | undefined): [number, number] {
  const tokens = [...(text ?? "").matchAll(TOKEN)].map((match) => match[0]);
  return tokens.length ? [month(tokens[0], false), month(tokens.at(-1)!, true)] : [0, 0];
}

export function entryDateKey(entry: ResumeEntry): [number, number] {
  const dated = entry as { start?: string; end?: string; dates?: string; date?: string };
  const [fallbackStart, fallbackEnd] = span(dated.dates || dated.date);
  const explicitStart = span(dated.start)[0],
    explicitEnd = span(dated.end)[1];
  if (!dated.dates && (explicitStart || explicitEnd))
    return [explicitEnd || explicitStart, explicitStart];
  const start = explicitStart || fallbackStart;
  return [explicitEnd || fallbackEnd || start, start];
}

export function isDatedSection(section: Section): boolean {
  return ["experience", "project", "education"].includes(section.kind);
}

export function orderResumeEntries(resume: MasterResume): MasterResume {
  let changed = false;
  const sections = resume.sections.map((section) => {
    if (!isDatedSection(section)) return section;
    const entries = [...section.entries].sort((a, b) => {
      const ak = entryDateKey(a),
        bk = entryDateKey(b);
      return bk[0] - ak[0] || bk[1] - ak[1];
    });
    if (entries.every((entry, index) => entry === section.entries[index])) return section;
    changed = true;
    return { ...section, entries } as Section;
  });
  return changed ? { ...resume, sections } : resume;
}
