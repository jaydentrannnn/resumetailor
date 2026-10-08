import { useState } from "react";
import { setApplicationNotes, type ApplicationRow } from "../../../api";
import { Button, Tile } from "../../../components/ui";
import { describe } from "../../../lib/errors";
import { useToast } from "../../../lib/toast";

/** The applicant's own notes on one application, saved on demand. */
export function NotesPanel({
  application,
  onSaved,
}: {
  application: ApplicationRow;
  onSaved: (updated: ApplicationRow) => void;
}) {
  const toast = useToast();
  const [text, setText] = useState(application.notes ?? "");
  const [saving, setSaving] = useState(false);
  const dirty = text !== (application.notes ?? "");
  async function save() {
    setSaving(true);
    try {
      onSaved(await setApplicationNotes(application.source_job_id, text));
      toast.success("Notes saved");
    } catch (reason) {
      toast.error("Could not save notes", describe(reason).detail);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Tile>
      <label className="rt-eyebrow mb-2 block" htmlFor="application-notes">
        Your notes
      </label>
      <textarea
        id="application-notes"
        className="field min-h-40 text-sm"
        maxLength={20000}
        placeholder="Recruiter name, interview dates, anything to remember."
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="mt-3 flex items-center gap-3">
        <Button variant="primary" disabled={!dirty || saving} onClick={() => void save()}>
          {saving ? "Saving…" : "Save notes"}
        </Button>
        {dirty && <span className="text-xs text-ink-muted">Unsaved changes</span>}
      </div>
    </Tile>
  );
}
