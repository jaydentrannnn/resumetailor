import { useEffect, useState } from "react";
import { type JobBullet, type RunHistoryEntry, fetchJobBullets } from "../api";
import { describe } from "../lib/errors";
import { type CompareGroup, compareCounts, compareRuns } from "../lib/runHistory";
import { Modal } from "./Modal";

const KIND_LABEL = {
  changed: "Worded differently",
  only_a: "Only in the first run",
  only_b: "Only in the second run",
} as const;

/** Two runs' final bullets side by side (read-only; nothing is changed). */
export function CompareRunsDialog({
  a,
  b,
  onClose,
}: {
  a: RunHistoryEntry;
  b: RunHistoryEntry;
  onClose: () => void;
}) {
  const [groups, setGroups] = useState<CompareGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSame, setShowSame] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([fetchJobBullets(a.job_id), fetchJobBullets(b.job_id)])
      .then(([left, right]: { bullets: JobBullet[] }[]) => {
        if (live) setGroups(compareRuns(left.bullets, right.bullets));
      })
      .catch((err) => live && setError(describe(err).detail));
    return () => {
      live = false;
    };
  }, [a.job_id, b.job_id]);

  const counts = groups ? compareCounts(groups) : null;
  const name = (run: RunHistoryEntry) =>
    run.company ? `${run.title} · ${run.company}` : run.title;

  return (
    <Modal title="Compare runs" onClose={onClose} wide>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <p>
          <span className="text-xs text-ink-muted">First</span>
          <br />
          <strong>{name(a)}</strong>
        </p>
        <p>
          <span className="text-xs text-ink-muted">Second</span>
          <br />
          <strong>{name(b)}</strong>
        </p>
      </div>
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      {!groups && !error && <p className="mt-3 text-sm text-ink-muted">Loading bullets…</p>}
      {counts && (
        <div
          className="mt-3 flex flex-wrap items-center gap-3 text-sm text-ink-muted"
          role="status"
        >
          <span>
            {counts.same} same · {counts.changed} worded differently · {counts.only_a} only in first
            · {counts.only_b} only in second
          </span>
          <label className="ml-auto flex items-center gap-2">
            <input
              type="checkbox"
              checked={showSame}
              onChange={(e) => setShowSame(e.target.checked)}
            />
            Show identical bullets
          </label>
        </div>
      )}
      <div className="mt-3 max-h-[60vh] space-y-4 overflow-y-auto">
        {groups?.map((g) => {
          const rows = showSame ? g.rows : g.rows.filter((r) => r.kind !== "same");
          if (rows.length === 0) return null;
          return (
            <div key={g.key}>
              <h4 className="text-sm font-semibold">
                {g.entry} <span className="font-normal text-ink-muted">· {g.section}</span>
              </h4>
              <ul className="mt-2 space-y-2">
                {rows.map((r) => (
                  <li key={r.bulletId} className="rounded-lg border border-line p-2 text-sm">
                    {r.kind !== "same" && (
                      <p className="text-micro font-semibold uppercase tracking-wide text-ink-muted">
                        {KIND_LABEL[r.kind]}
                      </p>
                    )}
                    <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <p className={r.a == null ? "text-ink-muted italic" : "text-ink"}>
                        {r.a ?? "Not used"}
                      </p>
                      <p className={r.b == null ? "text-ink-muted italic" : "text-ink"}>
                        {r.b ?? "Not used"}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {counts && counts.changed + counts.only_a + counts.only_b === 0 && !showSame && (
          <p className="text-sm text-ink-muted">Both runs used exactly the same bullets.</p>
        )}
      </div>
    </Modal>
  );
}
