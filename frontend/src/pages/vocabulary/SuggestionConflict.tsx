import { buttonClass } from "../../lib/buttonClass";
import type { useSuggestionsSection } from "./useSuggestionsSection";
type State = ReturnType<typeof useSuggestionsSection>;
export function SuggestionConflict({
  conflict,
  setConflict,
  doApprove,
}: Pick<State, "conflict" | "setConflict" | "doApprove">) {
  return (
    <>
      {" "}
      {conflict && (
        <div className="mt-4 space-y-3 border-t border-line pt-4">
          <p className="text-sm font-medium text-attn">{conflict.message}</p>
          <ul className="space-y-1 text-xs text-ink-muted">
            {conflict.impact.map((i) => (
              <li key={i.alias}>
                <span className="font-medium text-ink">{i.alias}</span> currently tags:{" "}
                {i.affected_bullets.map(([label]) => label).join(", ")}
              </li>
            ))}
          </ul>
          <p className="text-xs text-ink-muted">
            This permanently rewrites those tags the next time the master resume is saved. A backup
            will be saved first.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void doApprove(conflict.ids, true)}
              className={buttonClass("primary", "sm")}
            >
              Approve anyway
            </button>
            <button
              type="button"
              onClick={() => setConflict(null)}
              className={buttonClass("secondary", "sm")}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </>
  );
}
