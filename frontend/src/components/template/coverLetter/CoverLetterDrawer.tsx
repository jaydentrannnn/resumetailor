import { useState } from "react";
import type { CoverLetterField, CoverLetterSettings } from "../../../api";
import { describe } from "../../../lib/errors";
import { useToast } from "../../../lib/toast";
import { Button, Modal } from "../../ui";
import { CoverBlocksSection } from "./CoverBlocksSection";
import { CoverPreview } from "./CoverPreview";
import { LetterheadSection } from "./LetterheadSection";

/**
 * Edit cover-letter settings as a draft: the preview follows every change, and nothing
 * is saved until Save. Applies to every letter written from now on.
 */
export function CoverLetterDrawer({
  initial,
  fields,
  onSave,
  onClose,
}: {
  initial: CoverLetterSettings;
  fields: CoverLetterField[];
  onSave: (next: CoverLetterSettings) => Promise<void>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);

  async function save() {
    setSaving(true);
    try {
      await onSave(draft);
      toast.success("Cover letter settings saved");
      onClose();
    } catch (reason) {
      toast.error("Couldn't save cover letter settings", describe(reason).detail);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Cover letter" onClose={onClose} placement="right" size="lg">
      <p className="mt-1 text-sm text-ink-muted">
        Applies to every cover letter written from now on.
      </p>
      <div className="mt-5 space-y-5 text-sm">
        <LetterheadSection settings={draft} fields={fields} onChange={setDraft} />
        <CoverBlocksSection settings={draft} onChange={setDraft} />
        <CoverPreview settings={draft} />
      </div>
      <div className="sticky -bottom-5 -mx-5 mt-5 flex justify-end gap-2 border-t border-line bg-chrome px-5 py-3">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" loading={saving} disabled={!dirty} onClick={() => void save()}>
          Save
        </Button>
      </div>
    </Modal>
  );
}
