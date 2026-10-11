import type { CalibrationInfo } from "../../../api";
import { usePageFitTune } from "../../../lib/usePageFitTune";
import { useTemplateState } from "../../../state/templateState";
import { Button, DataList, StatusChip, TileSection } from "../../ui";

/**
 * Page fit: how precisely the app knows this template's line width and page length, so
 * it can keep a resume to the page count asked for, and a button to measure it again.
 */
export function PageFitSection({ calibration }: { calibration: CalibrationInfo }) {
  const { uploading, libraryBusy } = useTemplateState();
  const { running, log, tune } = usePageFitTune();
  const tuned = calibration.source !== "fallback" && !!calibration.calibrated_at;
  const needed = !tuned || calibration.stale;
  const status = !tuned ? "Not tuned yet" : calibration.stale ? "Out of date" : "Tuned";

  return (
    <TileSection
      title="Page fit"
      actions={<StatusChip tone={needed ? "attention" : "done"}>{status}</StatusChip>}
    >
      <DataList
        mono
        items={[
          { label: "Lines per page", value: calibration.lines_per_page },
          { label: "Characters per line", value: calibration.chars_per_line },
        ]}
      />
      <p className="mt-3 text-xs text-ink-muted">
        {tuned && calibration.calibrated_at
          ? `Measured ${new Date(calibration.calibrated_at).toLocaleString()}. `
          : ""}
        Tune again after switching templates or installing fonts.
      </p>
      {calibration.message && <p className="mt-2 text-xs text-attn">{calibration.message}</p>}
      <Button
        className="mt-3"
        variant={needed ? "attention" : "plain"}
        loading={running}
        disabled={uploading || libraryBusy}
        onClick={() => void tune()}
      >
        {running ? "Measuring…" : "Tune page fit"}
      </Button>
      {log && (
        <details className="mt-2 text-xs text-ink-muted">
          <summary className="cursor-pointer">Measurement log</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap">{log}</pre>
        </details>
      )}
    </TileSection>
  );
}
