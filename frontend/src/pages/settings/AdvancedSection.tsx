import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listResumeVersions, restoreResumeVersion, type ResumeVersion } from "../../api";
import type { MasterResume } from "../../lib/resumeEdit";
import { Button, Card } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import { useEditorState } from "../../state/editorState";
import { useRunState } from "../../state/runState";

/** Settings → Advanced: extraction votes, vocabulary, and master resume history. */
export function AdvancedSection() {
  const { settings, setSettings } = useRunState();
  return (
    <div className="space-y-6">
      <Card
        title="Job description reading"
        description="How many times the AI reads each posting before agreeing on its requirements. More reads are steadier but slower and cost more on paid models."
      >
        <select
          className="field max-w-xs"
          aria-label="Job description reads"
          value={settings.extract_runs}
          onChange={(e) => setSettings({ ...settings, extract_runs: Number(e.target.value) })}
        >
          <option value={0}>Automatic (1 on paid models, 3 on local ones)</option>
          <option value={1}>1 read</option>
          <option value={3}>3 reads</option>
          <option value={5}>5 reads</option>
        </select>
      </Card>
      <Card
        title="Skill vocabulary"
        description="Teach ResumeTailor that different spellings mean the same skill (for example, “MS Excel” and “Excel”)."
      >
        <Link
          to="/vocabulary"
          className="text-sm font-medium text-accent underline-offset-2 hover:underline"
        >
          Open vocabulary
        </Link>
      </Card>
      <ResumeHistory />
    </div>
  );
}

function ResumeHistory() {
  const toast = useToast();
  const { confirm } = useConfirm();
  const { dirty, syncFromDisk } = useEditorState();
  const [versions, setVersions] = useState<ResumeVersion[] | null>(null);
  const [keep, setKeep] = useState(50);
  const [restoring, setRestoring] = useState<number | null>(null);
  const load = useCallback(() => {
    listResumeVersions()
      .then((res) => {
        setVersions(res.versions);
        setKeep(res.keep);
      })
      .catch((err) => toast.error("Could not load resume history", describe(err).detail));
  }, [toast]);
  useEffect(load, [load]);

  async function restore(version: ResumeVersion) {
    const ok = await confirm({
      title: `Restore version ${version.version}?`,
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

  return (
    <Card
      title="Master resume history"
      description={`Every save is kept (the last ${keep}). Restore an earlier version if an edit or import went wrong.`}
    >
      {!versions ? (
        <p className="text-sm text-ink-muted">Loading…</p>
      ) : versions.length === 0 ? (
        <p className="text-sm text-ink-muted">No saved versions yet.</p>
      ) : (
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
      )}
    </Card>
  );
}
