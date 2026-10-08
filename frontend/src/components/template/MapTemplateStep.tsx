import { AnalyzeReport } from "./AnalyzeReport";
import { PreviewCompare } from "./PreviewCompare";
import { SectionMapStep } from "./SectionMapStep";
import type { useTemplateState } from "../../state/templateState";
type TemplateState = ReturnType<typeof useTemplateState>;
export function MapTemplateStep({
  state,
  importBusy,
  importContent,
}: {
  state: TemplateState;
  importBusy: boolean;
  importContent: (file: File) => Promise<void>;
}) {
  const {
    draftFile,
    analysis,
    uploading,
    beginAnalyze,
    profileDraft,
    setProfileDraft,
    headingOverrides,
    remapBusy,
    remapHeading,
  } = state;
  if (!analysis) return null;
  return (
    <>
      {" "}
      <p className="mt-4 text-sm text-ink-muted">
        File: <span className="font-medium text-ink">{draftFile?.name}</span>
      </p>
      <AnalyzeReport
        analysis={analysis}
        actions={{
          busy: uploading || importBusy,
          onConvertBullets: draftFile
            ? () => void beginAnalyze(draftFile, { convertBullets: true })
            : undefined,
          onImportContent: draftFile
            ? () =>
                void importContent(draftFile).then(() =>
                  document
                    .getElementById("starter-templates")
                    ?.scrollIntoView({ behavior: "smooth", block: "start" }),
                )
            : undefined,
        }}
      />
      {profileDraft ? (
        <>
          <SectionMapStep
            analysis={analysis}
            profile={profileDraft}
            onChange={setProfileDraft}
            headingOverrides={headingOverrides}
            remapBusy={remapBusy}
            onRemapHeading={(paragraphId, kind) => void remapHeading(paragraphId, kind)}
          />
          <PreviewCompare sourceSha256={analysis.source_sha256} profile={profileDraft} />
        </>
      ) : (
        <p className="mt-4 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger">
          No suggested mapping — see the issues above for what the analyzer could not map, fix the
          source document, and upload again.
        </p>
      )}
    </>
  );
}
