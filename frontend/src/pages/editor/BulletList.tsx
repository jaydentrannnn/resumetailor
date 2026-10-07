import { useState } from "react";
import { suggestTags, suggestTagsAI, type TagSuggestion } from "../../api";
import { ChipListField } from "../../components/ChipListField";
import { describe } from "../../lib/errors";
import { AddButton, EntryControls } from "../../components/ListControls";
import { useEditorState } from "../../state/editorState";
import { lintBullet, suggestMissingTags } from "../../lib/bulletLint";
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
  onEnsureVocab,
  pushUndo,
  onChange,
}: {
  bullets: Bullet[];
  vocabList: string[];
  takenIds: Set<string>;
  entryName: string;
  onEnsureVocab: (token: string) => void;
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

  const vocabSet = new Set(vocabList.map((t) => t.toLowerCase()));

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
          missing={suggestMissingTags(b.text, b.tags, vocabSet, vocabList)}
          softMin={softMin}
          charMax={charMax}
          charsPerLine={config?.chars_per_line ?? 0}
          onEnsureVocab={onEnsureVocab}
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
  missing,
  softMin,
  charMax,
  charsPerLine,
  onEnsureVocab,
  onMove,
  onRemove,
  onChange,
}: {
  bullet: Bullet;
  index: number;
  total: number;
  siblings: string[];
  vocabList: string[];
  missing: string[];
  softMin: number;
  charMax: number;
  charsPerLine: number;
  onEnsureVocab: (token: string) => void;
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
  onChange: (patch: Partial<Bullet>) => void;
}) {
  const [suggested, setSuggested] = useState<TagSuggestion[] | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [aiAsked, setAiAsked] = useState(false);
  const len = b.text.length;
  const overMax = len >= charMax;
  // The counter already warns past the character cap, and a ticked "has metric" means the
  // student knows the number (it may be spelled out), so those tips would only repeat.
  const hints = lintBullet(b.text, b.tags, { charsPerLine, siblings }).filter(
    (hint) => !(hint.code === "too_long" && overMax) && !(hint.code === "no_metric" && b.metric),
  );
  const tagged = new Set(b.tags.map((tag) => tag.toLowerCase()));
  // Local vocabulary hits first, then the server's alias matches, minus what is tagged.
  const chips = [
    ...missing.map((tag) => ({ tag, matched: "" })),
    ...(suggested ?? []).filter(
      (s) => !missing.some((tag) => tag.toLowerCase() === s.tag.toLowerCase()),
    ),
  ].filter((chip) => !tagged.has(chip.tag.toLowerCase()));

  function addTag(tag: string) {
    onEnsureVocab(tag);
    onChange({ tags: uniqueTags([...b.tags, tag]) });
  }

  async function suggest() {
    setSuggesting(true);
    setSuggestError(null);
    try {
      const res = await suggestTags(b.text, b.tags, vocabList);
      setSuggested(res.suggestions);
    } catch (reason) {
      setSuggestError(describe(reason).title);
    } finally {
      setSuggesting(false);
    }
  }

  /** Model fallback for a bullet no known skill matched; it only returns words the bullet says. */
  async function askAI() {
    setAsking(true);
    setSuggestError(null);
    try {
      const res = await suggestTagsAI(b.text, b.tags);
      setSuggested((current) => [...(current ?? []), ...res.suggestions]);
      setAiAsked(true);
    } catch (reason) {
      setSuggestError(describe(reason).title);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="border-l-2 border-line/60 pl-4">
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
          setSuggested(null);
          setAiAsked(false);
        }}
        className="w-full rounded-md border border-line bg-panel px-2 py-1.5 text-sm focus:border-accent"
      />
      <p
        className={`mt-1 text-xs tabular-nums ${
          overMax ? "text-warn" : len >= softMin ? "text-accent" : "text-ink-muted"
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
        <ul aria-label="Bullet tips" className="mt-1 space-y-0.5 text-xs text-ink-muted">
          {hints.map((hint) => (
            <li key={hint.code}>· {hint.message}</li>
          ))}
        </ul>
      )}
      <div className="mt-2">
        <ChipListField
          label="Tags"
          items={b.tags}
          suggestions={vocabList}
          onAddNew={onEnsureVocab}
          onChange={(tags) => onChange({ tags: uniqueTags(tags) })}
          placeholder="Add a tag"
        />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
        {chips.length > 0 && <span className="text-ink-muted">Mentioned but not tagged:</span>}
        {chips.map((chip) => (
          <button
            key={chip.tag}
            type="button"
            onClick={() => addTag(chip.tag)}
            title={chip.matched ? `Matched “${chip.matched}”` : undefined}
            className="rounded-full border border-accent/40 px-2 py-0.5 text-accent hover:bg-accent-soft"
          >
            + {chip.tag}
          </button>
        ))}
        {b.text.trim() && (
          <button
            type="button"
            onClick={() => void suggest()}
            disabled={suggesting}
            className="text-accent underline-offset-2 hover:underline disabled:opacity-50"
          >
            {suggesting ? "Looking…" : suggested ? "Suggest again" : "Suggest tags"}
          </button>
        )}
        {suggested && chips.length === 0 && (
          <span className="text-ink-muted">
            {aiAsked
              ? "The AI found no skills stated in this bullet."
              : "No skill from your vocabulary appears in this bullet."}
          </span>
        )}
        {suggested && chips.length === 0 && !aiAsked && (
          <button
            type="button"
            onClick={() => void askAI()}
            disabled={asking}
            className="text-accent underline-offset-2 hover:underline disabled:opacity-50"
          >
            {asking ? "Asking…" : "Ask AI"}
          </button>
        )}
        {suggestError && <span className="text-danger">{suggestError}</span>}
      </div>
    </div>
  );
}
