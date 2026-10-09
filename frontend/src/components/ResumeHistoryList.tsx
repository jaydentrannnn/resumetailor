import { useCallback, useEffect, useState } from "react";
import { listResumeVersions, restoreResumeVersion, type ResumeVersion } from "../api";
import { describe } from "../lib/errors";
import type { MasterResume } from "../lib/resumeEdit";
import { useToast } from "../lib/toast";
import { useConfirm } from "../state/confirmState";
import { useEditorState } from "../state/editorState";
import { Button, StatusChip } from "./ui";

const SHOWN_CHANGES = 3;

/** Saved versions grouped by the day they were saved, newest day first. */
function byDay(versions: ResumeVersion[]): [string, ResumeVersion[]][] {
  const groups = new Map<string, ResumeVersion[]>();
  for (const version of versions) {
    const day = new Date(version.saved_at).toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    groups.set(day, [...(groups.get(day) ?? []), version]);
  }
  return [...groups];
}

/** What a save changed: up to three lines, the rest behind "N more". */
function Changes({ version }: { version: ResumeVersion }) {
  const [all, setAll] = useState(false);
  if (version.changes === null)
    return (
      <span className="block text-xs text-ink-muted">
        Oldest kept version · {version.sections} sections · {version.bullets} bullets
      </span>
    );
  if (version.changes.length === 0)
    return <span className="block text-xs text-ink-muted">No visible changes</span>;
  const shown = all ? version.changes : version.changes.slice(0, SHOWN_CHANGES);
  const hidden = version.changes.length - shown.length;
  return (
    <ul className="mt-0.5 space-y-0.5 text-xs text-ink-2">
      {shown.map((line) => (
        <li key={line}>{line}</li>
      ))}
      {hidden > 0 && (
        <li>
          <button type="button" className="rt-link" onClick={() => setAll(true)}>
            {hidden} more change{hidden === 1 ? "" : "s"}
          </button>
        </li>
      )}
    </ul>
  );
}

/**
 * Saved master-resume versions, newest first and grouped by day, each with what it
 * changed and a Restore. `showUndo` adds "Undo last save" (restores the version before
 * the current one). A restore is itself saved as a new version, so it can be undone too.
 */
export function ResumeHistoryList({ showUndo = false }: { showUndo?: boolean }) {
  const toast = useToast();
  const { confirm } = useConfirm();
  const { dirty, syncFromDisk } = useEditorState();
  const [versions, setVersions] = useState<ResumeVersion[] | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);
  const load = useCallback(() => {
    listResumeVersions()
      .then((res) => setVersions(res.versions))
      .catch((err) => toast.error("Could not load resume history", describe(err).detail));
  }, [toast]);
  useEffect(load, [load]);

  async function restore(version: ResumeVersion, title = `Restore version ${version.version}?`) {
    const ok = await confirm({
      title,
      message: dirty
        ? "You have unsaved edits in the resume editor; they will be discarded. The current resume stays in history, so this can be undone."
        : "The current resume stays in history, so this can be undone.",
      confirmLabel: "Restore",
    });
    if (!ok) return;
    setRestoring(version.version);
    try {
      const res = await restoreResumeVersion(version.version);
      syncFromDisk(res.resume as MasterResume, `Restored version ${version.version}.`);
      toast.success(`Restored version ${version.version}`);
      load();
    } catch (err) {
      toast.error("Restore failed", describe(err).detail);
    } finally {
      setRestoring(null);
    }
  }

  if (!versions) return <p className="text-sm text-ink-muted">Loading…</p>;
  if (versions.length === 0)
    return <p className="text-sm text-ink-muted">No saved versions yet.</p>;
  const previous = versions.find((version) => !version.current);
  return (
    <div className="space-y-4">
      {showUndo && previous && (
        <Button
          loading={restoring === previous.version}
          disabled={restoring !== null}
          onClick={() => void restore(previous, "Undo the last save?")}
        >
          Undo last save
        </Button>
      )}
      {byDay(versions).map(([day, group]) => (
        <section key={day}>
          <h3 className="rt-eyebrow">{day}</h3>
          <ul className="divide-y divide-line">
            {group.map((version) => (
              <li key={version.version} className="flex items-start gap-3 py-2.5 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block text-ink">
                    {new Date(version.saved_at).toLocaleTimeString(undefined, {
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                    {version.note && <span className="text-ink-muted"> · {version.note}</span>}
                  </span>
                  <Changes version={version} />
                </span>
                {version.current ? (
                  <StatusChip tone="done">Current</StatusChip>
                ) : (
                  <Button
                    size="sm"
                    loading={restoring === version.version}
                    disabled={restoring !== null}
                    onClick={() => void restore(version)}
                  >
                    Restore
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
