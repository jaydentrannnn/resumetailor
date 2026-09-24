import type { ApplicantLanguage } from "../api";
import { AddButton, EntryControls } from "./ListControls";

/** Mirrors `profile.LANGUAGE_CATEGORIES` / `LANGUAGE_LEVELS`; forms' own wording is matched by rank. */
const LANGUAGE_CATEGORIES = ["Overall", "Reading", "Speaking", "Writing", "Comprehension"] as const;
const LANGUAGE_LEVELS = ["Beginner", "Intermediate", "Advanced", "Fluent", "Native"] as const;

type Props = { languages: ApplicantLanguage[]; onChange: (languages: ApplicantLanguage[]) => void };

/** Application-details list of spoken languages: name, fluency, and a level per category. */
export function LanguagesEditor({ languages, onChange }: Props) {
  function update(index: number, patch: Partial<ApplicantLanguage>) {
    onChange(languages.map((entry, i) => i === index ? { ...entry, ...patch } : entry));
  }
  function setLevel(index: number, category: string, level: string) {
    const levels = { ...languages[index].levels };
    if (level) levels[category] = level; else delete levels[category];
    update(index, { levels });
  }
  function move(from: number, to: number) {
    const next = [...languages];
    const [entry] = next.splice(from, 1);
    next.splice(to, 0, entry);
    onChange(next);
  }
  return <div className="mt-3 space-y-3">
    <p className="text-xs text-ink-muted">Filled into Workday's Languages section on My Experience, and into "What languages do you speak?" questions. Leave a level blank to answer it yourself.</p>
    {languages.map((entry, index) => <div key={index} className="rounded-md border border-line p-3" data-testid="language-row">
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-40 flex-1 text-sm">Language<input className="field mt-1" value={entry.language} placeholder="e.g. Vietnamese" onChange={e => update(index, { language: e.target.value })} /></label>
        <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={entry.fluent} onChange={e => update(index, { fluent: e.target.checked })} />I am fluent in this language</label>
        <EntryControls index={index} total={languages.length} onMove={move} onRemove={i => onChange(languages.filter((_, j) => j !== i))} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {LANGUAGE_CATEGORIES.map(category => <label key={category} className="text-sm">{category}<select className="field mt-1" value={entry.levels[category] ?? ""} onChange={e => setLevel(index, category, e.target.value)}><option value="">Not set</option>{LANGUAGE_LEVELS.map(level => <option key={level} value={level}>{level}</option>)}</select></label>)}
      </div>
    </div>)}
    <AddButton label="+ Add language" onClick={() => onChange([...languages, { language: "", fluent: false, levels: {} }])} />
  </div>;
}
