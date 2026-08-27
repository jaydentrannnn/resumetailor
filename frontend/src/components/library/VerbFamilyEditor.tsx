import { ChipListField } from "../ChipListField";
import { normalizeVerb, verbTokenError } from "../../lib/packValidation";

/** A verb-family "card": name input + Remove in the header, a chip box of verbs below. */
export function VerbFamilyCard({
  family,
  verbs,
  onFamilyChange,
  onVerbsChange,
  onRemove,
  error,
}: {
  family: string;
  verbs: string[];
  onFamilyChange: (family: string) => void;
  onVerbsChange: (verbs: string[]) => void;
  onRemove: () => void;
  /** Client-side validation message for this family as a whole (e.g. an empty-verbs
   * card, or a name colliding with another family in this pack), shown under the card. */
  error?: string | null;
}) {
  return (
    <div className="rounded-lg border border-line bg-paper/40 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <div className="w-40 flex-none">
          <input
            type="text"
            value={family}
            onChange={(e) => onFamilyChange(e.target.value)}
            placeholder="Family, e.g. care"
            className="field font-medium"
          />
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="ml-auto flex-none rounded-md border border-line px-2 py-1 text-xs text-ink-muted hover:border-danger hover:text-danger"
        >
          Remove
        </button>
      </div>
      <ChipListField
        ariaLabel={`Verbs in ${family || "new family"}`}
        items={verbs}
        onChange={onVerbsChange}
        normalize={normalizeVerb}
        validate={verbTokenError}
        separators={/[,\s]+/}
        placeholder="Type a verb and press Enter…"
      />
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
