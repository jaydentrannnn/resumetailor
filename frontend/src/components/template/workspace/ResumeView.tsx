import { useState, type ReactNode } from "react";
import { useLayoutSummary } from "../../../lib/useLayoutSummary";
import { useTemplateState } from "../../../state/templateState";
import { DataList } from "../../ui";
import { AdjustMode } from "../adjust/AdjustMode";
import { TemplatePreview } from "../TemplatePreview";
import { LookSection } from "./LookSection";
import { ResumeDetails } from "./ResumeDetails";
import { DOCUMENT_CELL, SWITCH_CELL, TOOLS_CELL, WORKSPACE_GRID } from "./workspaceLayout";

/**
 * Template page › Resume view: the template filled with the full master resume on the
 * left; on the right the view switch, what it is, its look and the technical details.
 * Quick adjustments swaps the whole view for its adjust mode until applied or cancelled.
 */
export function ResumeView({ switcher }: { switcher: ReactNode }) {
  const { info, previewKey, previewRevision, pendingTemplate } = useTemplateState();
  const layout = useLayoutSummary(previewRevision);
  const [adjusting, setAdjusting] = useState(false);
  if (!info) return null;
  if (adjusting) return <AdjustMode onDone={() => setAdjusting(false)} />;

  return (
    <div className={WORKSPACE_GRID} role="region" aria-label="Resume">
      <div className={SWITCH_CELL}>{switcher}</div>
      <div className={DOCUMENT_CELL}>
        <TemplatePreview
          revision={previewRevision}
          pending={pendingTemplate}
          refreshKey={previewKey}
        />
      </div>
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
            className="mt-4 flex-col"
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
        <LookSection summary={layout?.summary ?? null} onAdjust={() => setAdjusting(true)} />
        <ResumeDetails info={info} />
      </div>
    </div>
  );
}
