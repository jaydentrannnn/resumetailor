import type { useTemplateState } from "../../state/templateState";
import { FullOnly } from "../FullOnly";

/** The full wizard's result: installed or not, and (Full view) what the build printed. */
export function InstalledTemplateStep({ state }: { state: ReturnType<typeof useTemplateState> }) {
  const { error, wizardStep, lastBuildOk, info, calibrateAlso, buildLog } = state;
  const failed = wizardStep === "error" || lastBuildOk === false;
  return (
    <>
      {" "}
      {error && failed ? (
        <p className="mt-4 border-t border-line pt-4 text-sm text-danger">{error.split("\n")[0]}</p>
      ) : null}
      {lastBuildOk === true && wizardStep === "done" ? (
        <p className="mt-4 border-t border-line pt-4 text-sm text-accent">
          Template installed.
          {info?.calibration.stale
            ? " Page fit has not been tuned for it yet: press Tune page fit on the Template page."
            : calibrateAlso
              ? " Page fit was tuned for it."
              : null}
        </p>
      ) : null}
      {buildLog ? (
        // The build's own output (paths, backend, measured constants): Full view only,
        // unless the install failed and it is the evidence.
        <FullOnly keep={failed}>
          <pre className="mt-4 max-h-48 overflow-auto border-t border-line pt-4 text-xs text-ink whitespace-pre-wrap">
            {buildLog}
          </pre>
        </FullOnly>
      ) : null}
    </>
  );
}
