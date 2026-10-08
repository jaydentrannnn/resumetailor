import { UploadDropzone } from "./UploadDropzone";
import type { useTemplateState } from "../../state/templateState";
export function UploadTemplateStep({ state }: { state: ReturnType<typeof useTemplateState> }) {
  const { wizardStep, uploading, beginAnalyze } = state;
  return (
    <>
      {" "}
      {wizardStep === "idle" || wizardStep === "error" ? (
        <UploadDropzone
          disabled={uploading}
          onFile={(file) => void beginAnalyze(file)}
          label={
            uploading
              ? "Analyzing…"
              : wizardStep === "error"
                ? "Fix the source and drop a new Word file, or"
                : "Drop a Word file here, or"
          }
        />
      ) : null}
      {wizardStep === "analyzing" ? (
        <p className="mt-4 text-sm text-ink-muted">Analyzing document structure…</p>
      ) : null}
    </>
  );
}
