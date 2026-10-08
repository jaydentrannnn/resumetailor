import { Button, DataList, Page, PageHeader, Tile } from "../components/ui";
import { TemplatePreview } from "../components/template/TemplatePreview";
import { PageFitCard } from "../components/template/PageFitCard";
import { SavedTemplatesPanel } from "../components/template/SavedTemplatesPanel";
import { StarterTemplatesPanel } from "../components/template/StarterTemplatesPanel";
import { TemplateImportWizard } from "../components/template/TemplateImportWizard";
import { useTemplateState } from "../state/templateState";

/**
 * Format a byte count for the metadata panel (e.g. 1.2 MB).
 */
function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Format an ISO timestamp for display, or an em dash when missing.
 */
function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/**
 * Template tab: preview the current tagged template and import a new baseline.
 */
export function TemplatePage() {
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

  return (
    <Page>
      <PageHeader
        title="Template"
        eyebrow={`Active: ${info?.active_label || "No template"}`}
        description="The Word document every tailored resume is poured into. Only the words change; the look stays yours."
      />
      <Tile aria-label="Current template">
        <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
          <div className="min-w-0">
            {info?.tagged.exists ? (
              <TemplatePreview
                revision={previewRevision}
                pending={pendingTemplate}
                refreshKey={previewKey}
              />
            ) : (
              <p className="py-8 text-sm text-ink-muted">
                {loading
                  ? "Loading template info…"
                  : "No template yet. Pick a starter template below, or upload your own single-column Word file."}
              </p>
            )}
          </div>
          <div className="min-w-0 space-y-5">
            <h2 className="rt-tile-title">
              {pendingTemplate
                ? `Switching to ${pendingTemplate}…`
                : info?.active_label || "Current template"}
            </h2>
            <Button
              className="self-start"
              onClick={() => void refresh()}
              disabled={loading || uploading || libraryBusy}
            >
              Refresh
            </Button>
            <p className="text-sm text-ink-muted">
              Tagged template filled with your full master resume. Formatting comes from your
              uploaded single-column export.
            </p>
            {info && (
              <DataList
                className="flex-col"
                items={[
                  { label: "Layout", value: "Single column" },
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
            )}
            {info && (
              <details className="border-t border-line pt-4">
                <summary className="cursor-pointer text-sm font-medium">Technical details</summary>
                <DataList
                  className="mt-4"
                  mono
                  items={[
                    { label: "Active label", value: info.active_label || "—" },
                    {
                      label: "Tagged template",
                      value: info.tagged.exists
                        ? `${formatBytes(info.tagged.size_bytes)} · ${formatWhen(info.tagged.modified_at)}`
                        : "Missing — upload a baseline below",
                    },
                    {
                      label: "Baseline export",
                      value: info.baseline.exists
                        ? `${formatBytes(info.baseline.size_bytes)} · ${formatWhen(info.baseline.modified_at)}`
                        : "Missing",
                    },
                    {
                      label: "Profile",
                      value: info.profile?.exists
                        ? `v${info.profile.schema_version ?? "?"} · ${
                            Object.entries(info.profile.enabled ?? {})
                              .filter(([, on]) => on)
                              .map(([k]) => k)
                              .join(", ") || "experience"
                          }`
                        : "Legacy (no profile file)",
                    },
                  ]}
                />
              </details>
            )}
            {!!info?.profile?.warnings?.length && (
              <details className="border-t border-line pt-4 text-sm text-attn">
                <summary className="cursor-pointer">
                  Warnings ({info.profile.warnings.length})
                </summary>
                {info.profile.warnings.map((warning, index) => (
                  <p key={index} className="mt-2">
                    {warning}
                  </p>
                ))}
              </details>
            )}
          </div>
        </div>
      </Tile>
      {info?.tagged.exists && <PageFitCard calibration={info.calibration} />}
      <SavedTemplatesPanel />
      <StarterTemplatesPanel />
      <TemplateImportWizard />
    </Page>
  );
}
