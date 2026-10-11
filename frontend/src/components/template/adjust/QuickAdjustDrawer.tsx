import { useEffect, useState } from "react";
import {
  adjustTemplate,
  fetchEditedLayout,
  fetchTemplateAdjustments,
  type CurrentLayout,
} from "../../../api";
import { describe } from "../../../lib/errors";
import { hasAdjustments, toAdjustments } from "../../../lib/templateAdjust";
import { WIZARD_ANCHOR } from "../../../lib/useLayoutEditSession";
import { useTemplateState } from "../../../state/templateState";
import { Button, Modal, Spinner } from "../../ui";
import { FieldEmphasisTable } from "./FieldEmphasisTable";
import { PageAndFontSection } from "./PageAndFontSection";

/**
 * Quick adjustments as a draft. "Review" applies them to a copy of the layout and opens
 * it in the template wizard to preview and install as a new template; the current one
 * stays in Your templates, so switching back undoes it.
 */
export function QuickAdjustDrawer({ onClose }: { onClose: () => void }) {
  const { info, beginFromAnalysis } = useTemplateState();
  const [current, setCurrent] = useState<CurrentLayout | null>(null);
  const [draft, setDraft] = useState<CurrentLayout | null>(null);
  const [tableLayout, setTableLayout] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchTemplateAdjustments()
      .then((res) => {
        if (!live) return;
        setCurrent(res.current);
        setDraft(res.current);
        setTableLayout(res.table_layout);
      })
      .catch((reason) => live && setError(describe(reason).detail));
    return () => {
      live = false;
    };
  }, []);

  const adj = current && draft ? toAdjustments(current, draft) : {};

  async function review() {
    setBusy(true);
    setError(null);
    try {
      const analysis = await adjustTemplate(adj);
      const file = await fetchEditedLayout(analysis.source_sha256);
      beginFromAnalysis(file, analysis, `${info?.active_label || "Template"} (adjusted)`);
      onClose();
      document.getElementById(WIZARD_ANCHOR)?.scrollIntoView({ behavior: "smooth" });
    } catch (reason) {
      setError(describe(reason).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Quick adjustments" onClose={onClose} placement="right" size="lg">
      <p className="mt-1 text-sm text-ink-muted">
        Changes are previewed in the template importer below before anything is installed.
      </p>
      {!draft && !error && <Spinner />}
      {draft && (
        <div className="mt-5 space-y-5 text-sm">
          <PageAndFontSection draft={draft} tableLayout={tableLayout} onChange={setDraft} />
          <FieldEmphasisTable
            fields={draft.fields}
            onChange={(fields) => setDraft({ ...draft, fields })}
          />
        </div>
      )}
      {error && <p className="mt-4 text-sm text-danger">{error}</p>}
      <div className="sticky -bottom-5 -mx-5 mt-5 flex justify-end gap-2 border-t border-line bg-chrome px-5 py-3">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          loading={busy}
          disabled={!hasAdjustments(adj)}
          onClick={() => void review()}
        >
          Review changes
        </Button>
      </div>
    </Modal>
  );
}
