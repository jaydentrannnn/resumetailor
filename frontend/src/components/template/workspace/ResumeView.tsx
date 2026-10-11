import { useLayoutSummary } from "../../../lib/useLayoutSummary";
import { useTemplateState } from "../../../state/templateState";
import { Button, DataList } from "../../ui";
import { TemplatePreview } from "../TemplatePreview";
import { LookSection } from "./LookSection";
import { PageFitSection } from "./PageFitSection";
import { ResumeDetails } from "./ResumeDetails";
import { WORKSPACE_GRID } from "./workspaceLayout";

/**
 * Template page › Resume view: the template filled with the full master resume on the
 * left; on the right what it is, its look, its page fit and the technical details.
 */
export function ResumeView() {
  const {
    info,
    loading,
    uploading,
    previewKey,
    previewRevision,
    pendingTemplate,
    libraryBusy,
    refresh,
  } = useTemplateState();
  const layout = useLayoutSummary(previewRevision);
  if (!info) return null;

  return (
    <div className={WORKSPACE_GRID}>
      <div className="min-w-0">
        <TemplatePreview
          revision={previewRevision}
          pending={pendingTemplate}
          refreshKey={previewKey}
          activeLabel={info.active_label}
        />
      </div>
      <div className="min-w-0 space-y-5">
        <div>
          <div className="flex items-start justify-between gap-3">
            <h2 className="rt-tile-title min-w-0">
              {pendingTemplate
                ? `Switching to ${pendingTemplate}…`
                : info.active_label || "Current template"}
            </h2>
            <Button
              variant="plain"
              size="sm"
              onClick={() => void refresh()}
              disabled={loading || uploading || libraryBusy}
            >
              Refresh
            </Button>
          </div>
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
            ]}
          />
        </div>
        <LookSection summary={layout?.summary ?? null} />
        <PageFitSection calibration={info.calibration} />
        <ResumeDetails info={info} />
      </div>
    </div>
  );
}
