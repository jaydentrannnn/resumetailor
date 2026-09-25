import { useState } from "react";
import { calibrateTemplate, type CalibrationInfo } from "../../api";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useTemplateState } from "../../state/templateState";
import { Button } from "../ui";

/**
 * "Page fit tuning": how precisely the app knows this template's line width and page
 * length, when that was measured, and a button to measure it again.
 */
export function PageFitCard({ calibration }: { calibration: CalibrationInfo }) {
  const { refresh, uploading, libraryBusy } = useTemplateState();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string | null>(null);
  const tuned = calibration.source !== "fallback" && !!calibration.calibrated_at;
  const status = !tuned ? "Not tuned yet" : calibration.stale ? "Out of date" : "Tuned";
  const tone =
    !tuned || calibration.stale ? "bg-warn-soft text-warn" : "bg-accent-soft text-accent";

  async function tune() {
    setRunning(true);
    try {
      const result = await calibrateTemplate();
      setLog([result.log, ...result.warnings.map((w) => `warning: ${w}`)].join("\n").trim());
      if (result.ok) toast.success("Page fit tuned for this template");
      else toast.error("Couldn't tune page fit", result.log.split("\n")[0]);
      await refresh();
    } catch (reason) {
      toast.error("Couldn't tune page fit", describe(reason).detail);
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-display text-lg font-semibold">Page fit tuning</h2>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>{status}</span>
          </div>
          <p className="mt-1 max-w-prose text-sm text-ink-muted">
            The app measures how much text fits on a line and a page of this template, so it can
            keep your resume to the page count you ask for. Tune it again after switching templates
            or installing fonts.
          </p>
        </div>
        <Button
          variant={tuned && !calibration.stale ? "secondary" : "primary"}
          loading={running}
          disabled={uploading || libraryBusy}
          onClick={() => void tune()}
        >
          {running ? "Measuring…" : "Tune page fit"}
        </Button>
      </div>
      <p className="mt-3 text-sm">
        About <strong>{calibration.chars_per_line}</strong> characters per line and{" "}
        <strong>{calibration.lines_per_page}</strong> lines per page
        {tuned && calibration.calibrated_at
          ? ` · measured ${new Date(calibration.calibrated_at).toLocaleString()}`
          : " · estimated"}
        .
      </p>
      {calibration.message && <p className="mt-2 text-sm text-warn">{calibration.message}</p>}
      {log && (
        <details className="mt-2 text-xs text-ink-muted">
          <summary className="cursor-pointer">Measurement log</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap">{log}</pre>
        </details>
      )}
    </section>
  );
}
