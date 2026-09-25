import { useCallback, useEffect, useState } from "react";
import { listResumeVersions, restoreResumeVersion, type ResumeVersion } from "../api";
import { describe } from "../lib/errors";
import type { MasterResume } from "../lib/resumeEdit";
import { useToast } from "../lib/toast";
import { useConfirm } from "../state/confirmState";
import { useEditorState } from "../state/editorState";
import { Button } from "./ui";

/**
 * Saved master-resume versions, newest first, each with Restore. `showUndo` adds an
 * "Undo last save" button that restores the version before the current one. A restore
 * is itself saved as a new version, so it can be undone the same way.
 */
export function ResumeHistoryList({
  onKeep,
  showUndo = false,
}: {
  onKeep?: (keep: number) => void;
  showUndo?: boolean;
}) {
  const toast = useToast();
  const { confirm } = useConfirm();
  const { dirty, syncFromDisk } = useEditorState();
  const [versions, setVersions] = useState<ResumeVersion[] | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);
  const load = useCallback(() => {
    listResumeVersions()
      .then((res) => {
        setVersions(res.versions);
        onKeep?.(res.keep);
      })
      .catch((err) => toast.error("Could not load resume history", describe(err).detail));
  }, [toast, onKeep]);
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
    <div className="space-y-3">
      {showUndo && previous && (
        <Button
          loading={restoring === previous.version}
          disabled={restoring !== null}
          onClick={() => void restore(previous, "Undo the last save?")}
        >
          Undo last save
        </Button>
      )}
      <ul className="divide-y divide-line">
        {versions.map((version) => (
          <li key={version.version} className="flex flex-wrap items-center gap-3 py-2 text-sm">
            <span className="w-10 shrink-0 font-mono text-xs text-ink-muted">
              v{version.version}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-ink">
                {new Date(version.saved_at).toLocaleString()} · {version.note || "saved"}
              </span>
              <span className="block text-xs text-ink-muted">
                {version.sections} sections · {version.bullets} bullets
              </span>
            </span>
            {version.current ? (
              <span className="text-xs text-ink-muted">Current</span>
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
    </div>
  );
}
