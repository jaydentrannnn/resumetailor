import type { useTemplateState } from "../../state/templateState";
export function InstalledTemplateStep({ state }: { state: ReturnType<typeof useTemplateState> }) {
  const { error, wizardStep, lastBuildOk, info, calibrateAlso, buildLog } = state;
  return (
    <>
      {" "}
      {error && (wizardStep === "error" || lastBuildOk === false) ? (
        <p className="mt-4 border-t border-line pt-4 text-sm text-danger">{error.split("\n")[0]}</p>
      ) : null}
      {lastBuildOk === true && wizardStep === "done" ? (
        <p className="mt-4 border-t border-line pt-4 text-sm text-accent">
          Template rebuilt successfully.
          {info?.calibration.stale
            ? " Fit constants may still be stale — enable calibrate on the next install, or run calibrate.py."
            : calibrateAlso
              ? " Fit constants were recalibrated for this template."
              : null}
        </p>
      ) : null}
      {buildLog ? (
        <pre className="mt-4 max-h-48 overflow-auto border-t border-line pt-4 text-xs text-ink whitespace-pre-wrap">
          {buildLog}
        </pre>
      ) : null}
    </>
  );
}
