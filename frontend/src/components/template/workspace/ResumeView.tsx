import { useLayoutSummary } from "../../../lib/useLayoutSummary";
import { useTemplateState } from "../../../state/templateState";
import { DataList, TileLayout } from "../../ui";
import { AdjustMode } from "../adjust/AdjustMode";
import { PageFitCard } from "../PageFitCard";
import { TemplatePreview } from "../TemplatePreview";
import { LookSection } from "./LookSection";
import { ResumeDetails } from "./ResumeDetails";
import { DOCUMENT_CELL, TOOLS_CELL, WORKSPACE_GRID } from "./workspaceLayout";

/**
 * Template page › Resume view: the template filled with the full master resume on the
 * left; on the right what it is, its look, its page fit and the technical details, as
 * rows. Quick adjustments swaps the whole view for its adjust mode until applied or
 * cancelled.
 */
export function ResumeView({
  adjusting,
  onAdjusting,
}: {
  adjusting: boolean;
  onAdjusting: (on: boolean) => void;
}) {
  const { info, previewKey, previewRevision, pendingTemplate } = useTemplateState();
  const layout = useLayoutSummary(previewRevision);
  if (!info) return null;
  if (adjusting) return <AdjustMode onDone={() => onAdjusting(false)} />;

  return (
    <div className={WORKSPACE_GRID} role="region" aria-label="Resume">
      <div className={DOCUMENT_CELL}>
        <TemplatePreview
          revision={previewRevision}
          pending={pendingTemplate}
          refreshKey={previewKey}
        />
      </div>
      <TileLayout.Provider value="flat">
        <div className={TOOLS_CELL}>
          <div>
            <h2 className="rt-tile-title">
              {pendingTemplate
                ? `Switching to ${pendingTemplate}…`
                : info.active_label || "Current template"}
            </h2>
            <p className="mt-1 text-sm text-ink-muted">
              Your template filled with your full master resume. Only the words change when a resume
              is tailored.
            </p>
            <DataList
              className="mt-4"
              items={[
                { label: "Layout", value: layout?.table ? "Table" : "Single column" },
                {
                  label: "Master resume",
                  value: `${info.experience_entries} jobs · ${info.project_entries} projects · ${info.bullets} bullets`,
                },
                {
                  label: "Lines per page",
                  value: <span className="font-mono">{info.calibration.lines_per_page}</span>,
                },
              ]}
            />
          </div>
          <LookSection summary={layout?.summary ?? null} onAdjust={() => onAdjusting(true)} />
          <div className="border-t border-line pt-4">
            <PageFitCard calibration={info.calibration} />
          </div>
          <ResumeDetails info={info} />
        </div>
      </TileLayout.Provider>
    </div>
  );
}
