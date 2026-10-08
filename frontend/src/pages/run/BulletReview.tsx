import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJobBullets, rerenderJob, type JobBullet, type RerenderResult } from "../../api";
import { Button, ResultFrame } from "../../components/ui";
import {
  SEGMENT_BASE,
  SEGMENT_OFF,
  SEGMENT_ON,
  SEGMENT_TRACK,
} from "../../components/ui/Segmented";
import {
  type BulletMode,
  groupRows,
  initialReview,
  pendingCount,
  resetToAi,
  type ReviewState,
  toRequest,
} from "../../lib/bulletReview";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";

const MODES: { id: BulletMode; label: string }[] = [
  { id: "ai", label: "Keep" },
  { id: "edit", label: "Edit" },
  { id: "original", label: "Use original" },
  { id: "remove", label: "Remove" },
];

/**
 * Review the tailored bullets beside the master resume's wording, change any of them,
 * and render the document again. No AI call: the edited text goes into the run's own
 * template, and a result that no longer fits the page is refused, not cut.
 */
export function BulletReview({
  jobId,
  ready = true,
  onSaved,
  embedded = false,
}: {
  jobId: string;
  /** False while the run is still going: the bullets load once it finishes. */
  ready?: boolean;
  onSaved: () => void;
  /** Inside the Tailor page's "Last result" tile: no box of its own. */
  embedded?: boolean;
}) {
  const toast = useToast();
  const [rows, setRows] = useState<JobBullet[] | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [state, setState] = useState<ReviewState>({});
  const [busy, setBusy] = useState(false);
  const [flagged, setFlagged] = useState<Record<string, string[]>>({});
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const flagToast = useRef<number | null>(null);
  const [over, setOver] = useState<Extract<RerenderResult, { status: "over" }> | null>(null);

  const load = useCallback(() => {
    if (!ready) return;
    fetchJobBullets(jobId)
      .then((res) => {
        setRows(res.bullets);
        setState(initialReview(res.bullets));
        setUnavailable(null);
      })
      .catch((err) => setUnavailable(describe(err).detail));
  }, [jobId, ready]);
  useEffect(load, [load]);

  const groups = useMemo(() => groupRows(rows ?? []), [rows]);
  const pending = rows ? pendingCount(rows, state) : 0;

  if (!ready) {
    return (
      <p className="text-sm text-ink-muted">
        You can review and edit the bullets when the run finishes.
      </p>
    );
  }
  if (unavailable) {
    return <p className="text-sm text-ink-muted">{unavailable}</p>;
  }
  if (!rows) return <p className="text-sm text-ink-muted">Loading bullets…</p>;

  function choose(id: string, mode: BulletMode, text?: string) {
    setOver(null);
    setState((prev) => ({ ...prev, [id]: { mode, text: text ?? prev[id]?.text ?? "" } }));
  }

  async function submit() {
    if (!rows) return;
    setBusy(true);
    setOver(null);
    try {
      const result = await rerenderJob(jobId, toRequest(state, rows, confirmed));
      if (result.status === "needs_confirmation") {
        setFlagged(result.flagged);
        flagToast.current = toast.error(
          "Check the highlighted bullets",
          "Some words aren't in your master resume. Confirm they're accurate, then update again.",
        );
      } else if (result.status === "over") {
        setOver(result);
      } else {
        setFlagged({});
        setConfirmed([]);
        if (flagToast.current != null) toast.dismiss(flagToast.current);
        flagToast.current = null;
        toast.success(
          `Resume updated · ${result.pages} page${result.pages === 1 ? "" : "s"}`,
          result.warnings.join(" ") || undefined,
        );
        onSaved();
        load();
      }
    } catch (err) {
      toast.error("Could not update the resume", describe(err).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ResultFrame
      embedded={embedded}
      title="Review bullets"
      description="Your original wording is shown in grey above each tailored bullet. Changes are rendered into the same template with no AI involved."
    >
      <div className="space-y-6">
        {groups.map((group) => (
          <div key={group.key} className="space-y-3">
            <h4 className="text-sm font-semibold text-ink">
              {group.entry} <span className="font-normal text-ink-muted">· {group.section}</span>
            </h4>
            {group.rows.map((row) => {
              const choice = state[row.bullet_id] ?? { mode: "ai", text: row.ai_text };
              const terms = flagged[row.bullet_id];
              return (
                <div
                  key={row.bullet_id}
                  className={
                    terms
                      ? "rounded-sm bg-attn-soft p-3"
                      : "border-t border-line pt-3 first-of-type:border-t-0"
                  }
                >
                  <p className="text-xs text-ink-muted">
                    {row.merged_from.length > 0 ? "Combined from: " : "Original: "}
                    {row.source_text}
                  </p>
                  {choice.mode === "edit" ? (
                    <textarea
                      aria-label={`Edit bullet for ${group.entry}`}
                      className="field mt-2 text-sm"
                      rows={2}
                      value={choice.text}
                      onChange={(e) => choose(row.bullet_id, "edit", e.target.value)}
                    />
                  ) : (
                    <p
                      className={`mt-2 text-sm ${choice.mode === "remove" ? "text-ink-muted line-through" : "text-ink"}`}
                    >
                      {choice.mode === "original" ? row.source_text : row.ai_text}
                    </p>
                  )}
                  <div
                    role="radiogroup"
                    aria-label="What to do with this bullet"
                    className={`mt-2 ${SEGMENT_TRACK}`}
                  >
                    {MODES.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        role="radio"
                        aria-checked={choice.mode === m.id}
                        onClick={() =>
                          choose(
                            row.bullet_id,
                            m.id,
                            m.id === "edit" && choice.mode !== "edit"
                              ? choice.mode === "original"
                                ? row.source_text
                                : row.ai_text
                              : undefined,
                          )
                        }
                        className={`${SEGMENT_BASE} ${choice.mode === m.id ? SEGMENT_ON : SEGMENT_OFF}`}
                      >
                        {m.id === "original" && row.merged_from.length > 0
                          ? `Use ${row.merged_from.length} originals`
                          : m.label}
                      </button>
                    ))}
                  </div>
                  {terms && (
                    <label className="mt-2 flex items-start gap-2 text-sm text-attn">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={confirmed.includes(row.bullet_id)}
                        onChange={(e) =>
                          setConfirmed((prev) =>
                            e.target.checked
                              ? [...prev, row.bullet_id]
                              : prev.filter((id) => id !== row.bullet_id),
                          )
                        }
                      />
                      <span>
                        Not in your master resume: <strong>{terms.join(", ")}</strong>. This is
                        accurate.
                      </span>
                    </label>
                  )}
                </div>
              );
            })}
          </div>
        ))}
        {over && (
          <p role="alert" className="mt-4 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger">
            That comes to {over.pages} pages, {over.over_by_lines} line
            {over.over_by_lines === 1 ? "" : "s"} over your {over.target_pages}-page target. Shorten
            or remove a bullet; nothing was changed.
          </p>
        )}
      </div>
      <div className="sticky bottom-0 -mx-5 -mb-5 mt-4 flex flex-wrap items-center gap-3 rounded-b-sm border-t border-line bg-panel px-5 py-3 sm:-mx-6 sm:px-6">
        <span className="text-sm text-ink-muted" role="status">
          {pending === 0
            ? "No changes"
            : `${pending} change${pending === 1 ? "" : "s"} not applied yet`}
        </span>
        <Button
          variant="ghost"
          className="ml-auto"
          onClick={() => {
            setState(resetToAi(rows));
            setOver(null);
            setFlagged({});
          }}
          disabled={busy}
        >
          Reset to AI version
        </Button>
        <Button
          variant="primary"
          onClick={() => void submit()}
          loading={busy}
          disabled={pending === 0}
        >
          Update resume (no AI)
        </Button>
      </div>
    </ResultFrame>
  );
}
