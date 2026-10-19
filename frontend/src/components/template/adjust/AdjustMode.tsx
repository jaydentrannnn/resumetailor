import { adjustedLabel } from "../../../lib/templateAdjust";
import { useAdjustPreview } from "../../../lib/useAdjustPreview";
import { WIZARD_ANCHOR } from "../../../lib/useLayoutEditSession";
import { useQuickAdjust } from "../../../lib/useQuickAdjust";
import { useConfirm } from "../../../state/confirmState";
import { useTemplateState } from "../../../state/templateState";
import { Button, Spinner } from "../../ui";
import { DOCUMENT_CELL, TOOLS_CELL, WORKSPACE_GRID } from "../workspace/workspaceLayout";
import { AdjustPreviewPane } from "./AdjustPreviewPane";
import { AdjustSettings } from "./AdjustSettings";

/**
 * The Resume view while adjusting: the draft rendered on the left (refreshed a moment
 * after each change, nothing installed), the settings on the right.
 * Apply installs the result as "<name> (adjusted)", replacing an earlier one of that
 * name (the original is never touched); Cancel drops the draft. The view switch
 * is replaced by these two so a draft can't be left behind by switching views.
 */
export function AdjustMode({ onDone }: { onDone: () => void }) {
  const { info, library, beginFromAnalysis, refreshLibrary } = useTemplateState();
  const { confirm } = useConfirm();
  const label = adjustedLabel(info?.active_label);
  const q = useQuickAdjust(label, refreshLibrary);
  const preview = useAdjustPreview(q.adj);
  const draft = q.draft;
  const active = info?.active_label || "The current template";
  const existing = library.find((e) => e.label.toLowerCase() === label.toLowerCase());
  const note = !existing
    ? `Apply saves this as “${label}”; ${active} stays in Your templates.`
    : existing.is_active
      ? `Apply updates “${label}”.`
      : `Apply replaces your earlier “${label}”; ${active} stays as it is.`;

  async function cancel() {
    if (
      q.dirty &&
      !(await confirm({
        title: "Discard these adjustments?",
        message: "Your changes haven't been applied, so the template stays as it was.",
        confirmLabel: "Discard",
        cancelLabel: "Keep editing",
        tone: "danger",
      }))
    )
      return;
    onDone();
  }

  async function apply() {
    const outcome = await q.apply();
    if (!outcome) return;
    if (outcome.kind === "review") {
      beginFromAnalysis(outcome.file, outcome.analysis, label);
      onDone();
      window.setTimeout(
        () => document.getElementById(WIZARD_ANCHOR)?.scrollIntoView({ behavior: "smooth" }),
        0,
      );
      return;
    }
    onDone();
  }

  return (
    <div className={WORKSPACE_GRID} role="region" aria-label="Quick adjustments">
      <div className={DOCUMENT_CELL}>
        <AdjustPreviewPane pages={preview.pages} loading={preview.loading} error={preview.error} />
      </div>
      <div className={TOOLS_CELL}>
        <div>
          <div className="flex items-center justify-between gap-3">
            <h2 className="rt-tile-title">Quick adjustments</h2>
            <div className="flex shrink-0 gap-2">
              <Button variant="ghost" onClick={() => void cancel()} disabled={q.busy}>
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={q.busy}
                disabled={!q.dirty}
                onClick={() => void apply()}
              >
                Apply
              </Button>
            </div>
          </div>
          <p className="mt-1 text-sm text-ink-muted">{note}</p>
          {q.error && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {q.error}
            </p>
          )}
        </div>
        {!draft
          ? !q.error && <Spinner />
          : q.current && (
              <AdjustSettings
                current={q.current}
                draft={draft}
                onChange={q.setDraft}
                fonts={q.fonts}
                tableLayout={q.tableLayout}
              />
            )}
      </div>
    </div>
  );
}
