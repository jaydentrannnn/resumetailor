import { useState } from "react";
import type { MergePlan } from "../api";
import {
  duplicateTargets,
  pairNote,
  proposedPicks,
  reviewSummary,
  type MergePicks,
} from "../lib/mergeReview";

/**
 * The review list of a resume merge: each job and project in the uploaded file, with
 * the entry it would be folded into. The student can point it at another entry or keep
 * it as a new one before anything is saved. Shown in both views: it is the step that
 * stops one job becoming two.
 */
export function MergeReview({
  plan,
  onChange,
}: {
  plan: MergePlan;
  /** Every change to the picks; the dialog's caller reads the latest when it resolves. */
  onChange: (picks: MergePicks) => void;
}) {
  const [picks, setPicks] = useState<MergePicks>(() => proposedPicks(plan.pairs));
  const pick = (key: string, value: string) => {
    const next = { ...picks, [key]: value };
    setPicks(next);
    onChange(next);
  };
  return (
    <div className="mt-4 border-t border-line pt-4 text-sm">
      <p className="font-medium text-ink">Jobs and projects in the uploaded file</p>
      <ul className="mt-2 max-h-[45vh] space-y-3 overflow-auto pr-1">
        {plan.pairs.map((pair) => (
          <li key={pair.key} className="space-y-1">
            <label className="block">
              <span className="text-ink">{pair.name}</span>
              {pair.detail && <span className="ml-2 text-xs text-ink-muted">{pair.detail}</span>}
              <select
                className="field mt-1"
                value={picks[pair.key]}
                onChange={(e) => pick(pair.key, e.target.value)}
              >
                <option value="new">New entry</option>
                {plan.options
                  .filter((option) => option.kind === pair.kind)
                  // A suggested entry is listed first, right under "New entry".
                  .sort(
                    (a, b) => Number(b.ref === pair.suggested) - Number(a.ref === pair.suggested),
                  )
                  .map((option) => (
                    <option key={option.ref} value={option.ref}>
                      Same as: {option.label}
                    </option>
                  ))}
              </select>
            </label>
            <p className="text-xs text-ink-muted">{pairNote(pair, picks[pair.key])}</p>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-ink-muted" role="status">
        {reviewSummary(plan.pairs, picks)}.
      </p>
      {duplicateTargets(picks) && (
        <p className="mt-1 text-attn" role="alert">
          Two entries point at the same one. Only the first is merged into it; the other is matched
          by the app.
        </p>
      )}
    </div>
  );
}
