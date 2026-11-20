import { useEffect, useState } from "react";
import { fetchResumeDuplicates, mergeResumeDuplicates, type DuplicatePair } from "../api";
import { describe } from "../lib/errors";
import type { MasterResume } from "../lib/resumeEdit";
import { useEditorState } from "../state/editorState";
import { Button } from "./ui";

/**
 * "These look like the same job twice", with a Merge button per pair, on the Resume
 * page. It shows only when the saved resume has such a pair, in both views: it reports
 * a problem, and at rest it adds nothing. Hidden while there are unsaved edits, since
 * the pairs are worked out from the saved file.
 */
export function DuplicatesNotice() {
  const { resume, dirty, syncFromDisk } = useEditorState();
  const [pairs, setPairs] = useState<DuplicatePair[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (dirty || !resume) return;
    let live = true;
    fetchResumeDuplicates()
      .then((next) => live && setPairs(next))
      .catch(() => live && setPairs([]));
    return () => {
      live = false;
    };
  }, [dirty, resume]);

  async function merge(pair: DuplicatePair) {
    setBusy(true);
    setError(null);
    try {
      const result = await mergeResumeDuplicates(pair.keep, pair.drop);
      syncFromDisk(result.resume as MasterResume, `Merged into ${pair.keep_label}.`);
    } catch (err) {
      setError(describe(err).detail);
    } finally {
      setBusy(false);
    }
  }

  if (dirty || pairs.length === 0) return null;
  return (
    <div role="status" className="space-y-2 border-t border-line pt-4 text-sm">
      <p className="font-medium text-ink">
        {pairs.length === 1
          ? "This looks like the same entry twice"
          : "These look like the same entry twice"}
      </p>
      <ul className="space-y-2">
        {pairs.map((pair) => (
          <li key={pair.keep + pair.drop} className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-ink">
              {pair.keep_label} <span className="text-ink-muted">and</span> {pair.drop_label}
            </span>
            <span className="text-xs text-ink-muted">({pair.reason})</span>
            <Button size="sm" disabled={busy} onClick={() => void merge(pair)}>
              Merge into the first
            </Button>
          </li>
        ))}
      </ul>
      <p className="text-xs text-ink-muted">
        Merging keeps every bullet from both and backs up your resume first. If they are two
        different entries, leave them as they are.
      </p>
      {error && <p className="text-danger">{error}</p>}
    </div>
  );
}
