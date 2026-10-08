import { Tile } from "../../components/ui";
import { useState } from "react";
import { AddButton, EntryControls } from "../../components/ListControls";
import { EducationEntries } from "./EducationEntries";
import { ExperienceEntries } from "./ExperienceEntries";
import { ProjectEntries } from "./ProjectEntries";
import { ListEntries } from "./ListEntries";
import { SkillsEntries } from "./SkillsEntries";
import {
  type Section,
  type SectionKind,
  DEFAULT_SECTION_TITLES,
  SECTION_KIND_LABELS,
  SECTION_PRESETS,
} from "../../lib/resumeEdit";

export function AddSectionPanel({ onAdd }: { onAdd: (kind: SectionKind, title: string) => void }) {
  const kinds: SectionKind[] = ["experience", "project", "list", "education", "skills"];
  const [choice, setChoice] = useState("0");
  const [kind, setKind] = useState<SectionKind>("experience");
  const [title, setTitle] = useState("");
  const preset = choice === "custom" ? null : SECTION_PRESETS[Number(choice)];

  return (
    <Tile className="flex flex-wrap items-end gap-3">
      <label className="text-sm text-ink-muted">
        <span className="mb-1 block">New section</span>
        <select value={choice} onChange={(e) => setChoice(e.target.value)} className="field">
          {SECTION_PRESETS.map((item, index) => (
            <option key={item.title} value={String(index)}>
              {item.title} · {item.hint}
            </option>
          ))}
          <option value="custom">Something else…</option>
        </select>
      </label>
      {!preset && (
        <>
          <label className="text-sm text-ink-muted">
            <span className="mb-1 block">Title</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={DEFAULT_SECTION_TITLES[kind]}
              className="field"
            />
          </label>
          <label className="text-sm text-ink-muted">
            <span className="mb-1 block">Laid out like</span>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as SectionKind)}
              className="field"
            >
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {SECTION_KIND_LABELS[k]}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      <AddButton
        label="Add section"
        onClick={() =>
          preset
            ? onAdd(preset.kind, preset.title)
            : onAdd(kind, title.trim() || DEFAULT_SECTION_TITLES[kind])
        }
      />
    </Tile>
  );
}

export function SectionShell({
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
    <Tile className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={section.title}
              onChange={(e) => onChange({ ...section, title: e.target.value } as Section)}
              placeholder="Section title"
              className="min-h-9 w-full max-w-sm rounded-sm border border-transparent bg-transparent text-[15px] font-semibold hover:border-line focus:border-accent"
            />
            <span className="shrink-0 font-mono text-xs text-ink-muted">
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
    </Tile>
  );
}
