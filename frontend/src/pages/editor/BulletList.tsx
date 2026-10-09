import { StatusMark } from "../../components/ui";
import { ChipListField } from "../../components/ChipListField";
import { AddButton, EntryControls } from "../../components/ListControls";
import { useEditorState } from "../../state/editorState";
import { useBulletSkills } from "../../state/bulletSkillsState";
import { lintBullet } from "../../lib/bulletLint";
import {
  type Bullet,
  blankBullet,
  entryPrefix,
  insertAt,
  moveItem,
  nextBulletId,
  removeAt,
  uniqueTags,
} from "../../lib/resumeEdit";

export function BulletList({
  bullets,
  vocabList,
  takenIds,
  entryName,
  pushUndo,
  onChange,
}: {
  bullets: Bullet[];
  vocabList: string[];
  takenIds: Set<string>;
  entryName: string;
  pushUndo: (message: string) => void;
  onChange: (b: Bullet[]) => void;
}) {
  const { config } = useEditorState();
  const softMin = config?.bullet_char_soft_min ?? 172;
  const charMax = config?.bullet_char_max ?? 197;

  function addBullet() {
    const prefix = entryPrefix(bullets, entryName);
    const id = nextBulletId(prefix, takenIds);
    onChange(insertAt(bullets, 0, blankBullet(id)));
  }

  function removeBullet(idx: number) {
    const text = bullets[idx]?.text.trim();
    pushUndo(
      `Removed bullet${text ? ` “${text.slice(0, 40)}${text.length > 40 ? "…" : ""}”` : ""}`,
    );
    onChange(removeAt(bullets, idx));
  }

  function update(index: number, patch: Partial<Bullet>) {
    const next = [...bullets];
    next[index] = { ...bullets[index], ...patch };
    onChange(next);
  }

  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-ink-muted">Bullets</h3>
        <AddButton label="Add bullet" onClick={addBullet} />
      </div>
      {bullets.map((b, i) => (
        <BulletRow
          key={b.id}
          bullet={b}
          index={i}
          total={bullets.length}
          siblings={bullets.filter((other) => other.id !== b.id).map((other) => other.text)}
          vocabList={vocabList}
          softMin={softMin}
          charMax={charMax}
          charsPerLine={config?.chars_per_line ?? 0}
          onMove={(from, to) => onChange(moveItem(bullets, from, to))}
          onRemove={removeBullet}
          onChange={(patch) => update(i, patch)}
        />
      ))}
    </div>
  );
}

function BulletRow({
  bullet: b,
  index,
  total,
  siblings,
  vocabList,
  softMin,
  charMax,
  charsPerLine,
  onMove,
  onRemove,
  onChange,
}: {
  bullet: Bullet;
  index: number;
  total: number;
  siblings: string[];
  vocabList: string[];
  softMin: number;
  charMax: number;
  charsPerLine: number;
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
  onChange: (patch: Partial<Bullet>) => void;
}) {
  const len = b.text.length;
  const overMax = len >= charMax;
  // The counter already warns past the character cap, and a ticked "has metric" means the
  // student knows the number (it may be spelled out), so those tips would only repeat.
  const hints = lintBullet(b.text, { charsPerLine, siblings }).filter(
    (hint) => !(hint.code === "too_long" && overMax) && !(hint.code === "no_metric" && b.metric),
  );
  return (
    <div className="border-t border-line pt-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
        <code>{b.id}</code>
        <div className="flex items-center gap-2">
          <label className="inline-flex items-center gap-1">
            <input
              type="checkbox"
              checked={Boolean(b.metric)}
              onChange={(e) => onChange({ metric: e.target.checked })}
            />
            has metric
          </label>
          <EntryControls index={index} total={total} onMove={onMove} onRemove={onRemove} />
        </div>
      </div>
      <textarea
        value={b.text}
        rows={3}
        aria-label={`Bullet ${b.id}`}
        onChange={(e) => {
          onChange({ text: e.target.value });
        }}
        className="field"
      />
      <p
        className={`mt-1 text-xs tabular-nums ${
          overMax ? "text-attn" : len >= softMin ? "text-accent" : "text-ink-muted"
        }`}
      >
        {len} / {charMax}
        {overMax
          ? " — likely to wrap onto a near-empty line"
          : len >= softMin
            ? " (in target band)"
            : ""}
      </p>
      {hints.length > 0 && (
        <ul aria-label="Bullet tips" className="mt-2 space-y-1 text-xs text-attn">
          {hints.map((hint) => (
            <li key={hint.code} className="flex items-start gap-2">
              <StatusMark tone="attention" />
              <span>{hint.message}</span>
            </li>
          ))}
        </ul>
      )}
      <BulletSkillsLine bulletId={b.id} />
      <ExtraSkills
        tags={b.tags}
        vocabList={vocabList}
        onChange={(tags) => onChange({ tags: uniqueTags(tags) })}
      />
    </div>
  );
}

/** Read-only: what this saved bullet already shows (detected in its words, or inferred). */
function BulletSkillsLine({ bulletId }: { bulletId: string }) {
  const skills = useBulletSkills();
  const shown = skills?.bullets[bulletId] ?? [];
  if (shown.length === 0 && !skills?.running) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
      <span>Skills it shows:</span>
      {shown.map((skill) => (
        <span key={skill} className="rounded-sm border border-line px-1.5 py-0.5 text-ink">
          {skill}
        </span>
      ))}
      {skills?.running && <span>Detecting skills…</span>}
    </div>
  );
}

/** Optional skills the words don't name. Collapsed: most bullets never need one. */
function ExtraSkills({
  tags,
  vocabList,
  onChange,
}: {
  tags: string[];
  vocabList: string[];
  onChange: (tags: string[]) => void;
}) {
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-ink-muted hover:text-ink">
        Extra skills{tags.length > 0 ? ` (${tags.length})` : ""}
      </summary>
      <p className="mt-1 text-ink-muted">
        Skills this bullet demonstrates that its words don&apos;t name. Rewrites may mention them,
        so add only what you really used.
      </p>
      <div className="mt-1">
        <ChipListField
          label="Extra skills"
          items={tags}
          suggestions={vocabList}
          onChange={onChange}
          placeholder="Add a skill"
        />
      </div>
    </details>
  );
}
