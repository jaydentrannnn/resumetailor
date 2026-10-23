import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getFollowUpsDue, markNoReply, type FollowUpRow, type FollowUpsDue } from "../../api";
import { AttentionRow } from "../../components/ProfileGapsNotice";
import { Button, buttonClass, Modal } from "../../components/ui";
import { followUpSummary } from "../../lib/followUps";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";

function Rows({ rows, label }: { rows: FollowUpRow[]; label: (row: FollowUpRow) => string }) {
  return (
    <ul className="divide-y divide-line text-[13px]">
      {rows.map((row) => (
        <li key={row.application_id} className="flex items-center gap-3 py-2">
          <span className="min-w-0 flex-1 truncate text-ink">
            {row.company} · {row.role}
          </span>
          <span className="shrink-0 text-xs text-ink-muted">{label(row)}</span>
          <Link
            aria-label={`Open ${row.company} ${row.role}`}
            className={buttonClass("plain", "sm", "rt-row-action shrink-0")}
            to={`/applications/${encodeURIComponent(row.application_id)}?tab=outcome`}
          >
            Open
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * One Apply-page line when sent applications are due a follow-up or thank-you, or have
 * been silent for 60+ days. Review lists them; "Mark as no reply" records ``ghosted`` on
 * the silent ones after a confirmation (never "rejected").
 */
/** Rows due a note that aren't silent; silent ones are listed under "No reply". */
const nudges = (due: FollowUpsDue) => due.due.filter((row) => !row.stale);

export function FollowUpsNotice({
  revision,
  onChanged,
}: {
  revision: number;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [due, setDue] = useState<FollowUpsDue | null>(null);
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    getFollowUpsDue()
      .then((result) => live && setDue(result))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [revision, reload]);

  const summary = due ? followUpSummary(due) : "";
  if (!due || !summary) return null;

  async function noReply() {
    setBusy(true);
    try {
      const result = await markNoReply(due!.stale.map((row) => row.application_id));
      toast.success(`Marked ${result.updated.length} as no reply`);
      setConfirming(false);
      setReload((n) => n + 1);
      onChanged();
    } catch (reason) {
      toast.error("Could not save", describe(reason).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <AttentionRow
        label="Follow up"
        text={summary}
        action={
          <Button variant="plain" size="sm" className="rt-row-action" onClick={() => setOpen(true)}>
            Review
          </Button>
        }
      />
      {open && (
        <Modal title="Follow-ups" onClose={() => setOpen(false)} size="lg">
          <div className="space-y-5">
            {nudges(due).length > 0 && (
              <section className="space-y-1">
                <h3 className="text-xs font-semibold text-ink-2">Due a note</h3>
                <Rows
                  rows={nudges(due)}
                  label={(row) =>
                    row.due === "thank_you" ? "Thank-you" : `Sent ${row.days_since_sent} days ago`
                  }
                />
              </section>
            )}
            {due.stale.length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold text-ink-2">No reply in 60+ days</h3>
                <Rows rows={due.stale} label={(row) => `${row.days_since_sent} days`} />
                {confirming ? (
                  <div className="flex flex-wrap items-center gap-2 text-[13px]">
                    <span className="text-ink-2">
                      Record "No reply" on these {due.stale.length}? You can remove it later.
                    </span>
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={busy}
                      onClick={() => void noReply()}
                    >
                      Mark {due.stale.length} as no reply
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button size="sm" variant="secondary" onClick={() => setConfirming(true)}>
                    Mark all as no reply…
                  </Button>
                )}
              </section>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
