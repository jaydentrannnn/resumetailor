import type { VocabularyEntry, VocabularyItem, VocabularyKind } from "../../api";
import { buttonClass } from "../../components/ui";
import { useLibraryState } from "../../state/libraryState";

/** One spelling or verb. Built-in: hide/show. Yours: tinted, removable. */
function ItemChip({ item, kind }: { item: VocabularyItem; kind: VocabularyKind }) {
  const { busy, remove, setHidden } = useLibraryState();
  const tone = item.builtin
    ? "border-line bg-panel text-ink"
    : "border-transparent bg-accent-soft text-ink";
  const action = !item.builtin
    ? { label: `Remove ${item.value}`, glyph: "×", run: () => remove(kind, item.value) }
    : item.hidden
      ? {
          label: `Show ${item.value} again`,
          glyph: "↺",
          run: () => setHidden(kind, item.value, false),
        }
      : { label: `Hide ${item.value}`, glyph: "×", run: () => setHidden(kind, item.value, true) };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-xs font-medium ${tone} ${
        item.hidden ? "text-ink-muted line-through" : ""
      }`}
    >
      {item.value}
      <button
        type="button"
        aria-label={action.label}
        title={action.label}
        disabled={busy}
        onClick={() => void action.run()}
        className="flex min-h-6 min-w-6 items-center justify-center rounded-xs text-ink-muted no-underline hover:bg-sunken hover:text-ink"
      >
        {action.glyph}
      </button>
    </span>
  );
}

/** One term with its spellings, or one verb family with its verbs. */
export function EntryRow({ entry }: { entry: VocabularyEntry }) {
  const { busy, remove, setHidden } = useLibraryState();
  const isTerm = entry.kind === "term";
  const itemKind: VocabularyKind = isTerm ? "alias" : "verb";
  return (
    <li className="flex items-start gap-3 border-b border-line px-1 py-2 last:border-b-0">
      <div className="w-56 shrink-0 pt-1">
        <span className={`font-medium ${entry.hidden ? "text-ink-muted line-through" : ""}`}>
          {entry.name}
        </span>
        <span className="ml-2 text-xs text-ink-muted">
          {isTerm ? "" : "verbs"}
          {!entry.builtin && "yours"}
          {entry.hidden && "hidden"}
        </span>
      </div>
      <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
        {entry.items.map((item) => (
          <ItemChip key={item.value} item={item} kind={itemKind} />
        ))}
      </div>
      {isTerm && (
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            void (entry.builtin
              ? setHidden("term", entry.name, !entry.hidden)
              : remove("term", entry.name))
          }
          className={buttonClass("plain", "sm", "rt-row-action shrink-0")}
        >
          {!entry.builtin ? "Remove" : entry.hidden ? "Show" : "Hide"}
        </button>
      )}
    </li>
  );
}
