import { adjustedLabel } from "../../../lib/templateAdjust";
import { useAdjustPreview } from "../../../lib/useAdjustPreview";
import { WIZARD_ANCHOR } from "../../../lib/useLayoutEditSession";
import { useQuickAdjust } from "../../../lib/useQuickAdjust";
import { useConfirm } from "../../../state/confirmState";
import { useTemplateState } from "../../../state/templateState";
import { Button, Spinner } from "../../ui";
import { ADJUST_GRID, DOCUMENT_CELL, SWITCH_CELL, TOOLS_CELL } from "../workspace/workspaceLayout";
import { AdjustPreviewPane } from "./AdjustPreviewPane";
import { FieldEmphasisTable } from "./FieldEmphasisTable";
import { BulletsSection, LinksSection, SeparatorsSection } from "./MarksSections";
import { FontSection, PageSection } from "./PageFontSections";

/**
 * The Resume view while adjusting: the draft rendered on the left (refreshed a moment
 * after each change, nothing installed), the settings on the right in a wider column.
 * Apply installs the result as a new template; Cancel drops the draft. The view switch
 * is replaced by these two so a draft can't be left behind by switching views.
 */
export function AdjustMode({ onDone }: { onDone: () => void }) {
  const { info, beginFromAnalysis, refreshLibrary } = useTemplateState();
  const { confirm } = useConfirm();
  const label = adjustedLabel(info?.active_label);
  const q = useQuickAdjust(label, refreshLibrary);
  const preview = useAdjustPreview(q.adj);
  const draft = q.draft;

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
    <div className={ADJUST_GRID} role="region" aria-label="Quick adjustments">
      <div className={SWITCH_CELL}>
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
        <p className="mt-1 text-sm text-ink-muted">
          Apply saves this as a new template; the current one stays in Your templates.
        </p>
        {q.error && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {q.error}
          </p>
        )}
      </div>
      <div className={DOCUMENT_CELL}>
        <div className="lg:sticky lg:top-5">
          <AdjustPreviewPane
            pages={preview.pages}
            loading={preview.loading}
            error={preview.error}
          />
        </div>
      </div>
      <div className={TOOLS_CELL}>
        {!draft ? (
          !q.error && <Spinner />
        ) : (
          <>
            <PageSection draft={draft} onChange={q.setDraft} tableLayout={q.tableLayout} />
            <FontSection draft={draft} onChange={q.setDraft} fonts={q.fonts} />
            <BulletsSection draft={draft} onChange={q.setDraft} />
            <SeparatorsSection draft={draft} onChange={q.setDraft} />
            <LinksSection draft={draft} onChange={q.setDraft} />
            <FieldEmphasisTable
              fields={draft.fields}
              onChange={(fields) => q.setDraft({ ...draft, fields })}
            />
          </>
        )}
      </div>
    </div>
  );
}
