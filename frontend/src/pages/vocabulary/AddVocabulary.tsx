import { useId, useState } from "react";
import { buttonClass } from "../../components/ui";
import { familyNames, isVerbShaped, termNames } from "../../lib/vocabularySearch";
import { useLibraryState } from "../../state/libraryState";

/**
 * Shown when the search finds no exact match: add the word as a new term, as another
 * name for an existing term, or (for a single word) as an opening verb in a family.
 */
export function AddVocabulary({ word, onAdded }: { word: string; onAdded: () => void }) {
  const { entries, busy, add } = useLibraryState();
  const [term, setTerm] = useState("");
  const [family, setFamily] = useState("");
  const [error, setError] = useState<string | null>(null);
  const listId = useId();
  const value = word.trim();

  async function run(kind: "term" | "alias" | "verb", target = "") {
    setError(null);
    try {
      await add(kind, value, target);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="rounded-sm border border-dashed border-line-hover bg-sunken px-4 py-3 text-sm">
      <p>
        <span className="font-medium">“{value}”</span> isn't in the dictionary yet.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void run("term")}
          className={buttonClass("primary", "sm")}
        >
          Add as a new term
        </button>
        <span className="text-ink-muted">or another name for</span>
        <input
          list={listId}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="Pick a term…"
          aria-label="Term it is another name for"
          className="field w-44"
        />
        <datalist id={listId}>
          {termNames(entries).map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <button
          type="button"
          disabled={busy || !term.trim()}
          onClick={() => void run("alias", term)}
          className={buttonClass("plain", "sm")}
        >
          Add
        </button>
      </div>
      {isVerbShaped(value) && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-ink-muted">or an opening verb like</span>
          <select
            value={family}
            onChange={(e) => setFamily(e.target.value)}
            aria-label="Verb family"
            className="field w-auto"
          >
            <option value="">Choose a family…</option>
            {familyNames(entries).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy || !family}
            onClick={() => void run("verb", family)}
            className={buttonClass("plain", "sm")}
          >
            Add verb
          </button>
        </div>
      )}
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </div>
  );
}
