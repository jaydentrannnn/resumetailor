import { Page, PageHeader } from "../components/ui";
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
      <PageHeader title="Template" />
      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-semibold">
              {pendingTemplate
                ? `Switching to ${pendingTemplate}…`
                : info?.active_label || "Current template"}
            </h2>
            <p className="mt-1 text-sm text-ink-muted">
              Tagged template filled with your full master resume. Formatting comes from your
              uploaded single-column export; only the words change when you tailor.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading || uploading || libraryBusy}
            className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
          >
            Refresh
          </button>
        </div>

        {loading && !info ? (
          <p className="mt-4 text-sm text-ink-muted">Loading template info…</p>
        ) : info ? (
          <>
            <div className="flex flex-col">
              <details className="order-2 mt-4 border-t border-line pt-3">
                <summary className="cursor-pointer text-sm font-semibold">
                  Technical details
                </summary>
                <dl className="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
                  <MetaItem label="Active label" value={info.active_label || "—"} />
                  <MetaItem
                    label="Tagged template"
                    value={
                      info.tagged.exists
                        ? `${formatBytes(info.tagged.size_bytes)} · ${formatWhen(info.tagged.modified_at)}`
                        : "Missing — upload a baseline below"
                    }
                  />
                  <MetaItem
                    label="Baseline export"
                    value={
                      info.baseline.exists
                        ? `${formatBytes(info.baseline.size_bytes)} · ${formatWhen(info.baseline.modified_at)}`
                        : "Missing"
                    }
                  />
                  <MetaItem
                    label="Master resume"
                    value={`${info.experience_entries} jobs · ${info.project_entries} projects · ${info.bullets} bullets`}
                  />
                  <MetaItem
                    label="Profile"
                    value={
                      info.profile?.exists
                        ? `v${info.profile.schema_version ?? "?"} · ${
                            Object.entries(info.profile.enabled ?? {})
                              .filter(([, on]) => on)
                              .map(([k]) => k)
                              .join(", ") || "experience"
                          }`
                        : "Legacy (no profile file)"
                    }
                  />
                </dl>
              </details>

              {info.profile?.warnings?.length ? (
                <details className="order-3 mt-4 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
                  <summary className="cursor-pointer">
                    Warnings ({info.profile.warnings.length})
                  </summary>
                  {info.profile.warnings.map((warning, index) => (
                    <p key={index} className="mt-2">
                      {warning}
                    </p>
                  ))}
                </details>
              ) : null}

              {info.tagged.exists ? (
                <TemplatePreview
                  revision={previewRevision}
                  pending={pendingTemplate}
                  refreshKey={previewKey}
                />
              ) : (
                <p className="order-1 mt-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                  No template yet. Pick a starter template below, or upload your own single-column
                  Word file.
                </p>
              )}
            </div>
          </>
        ) : null}
      </section>

      {info?.tagged.exists && <PageFitCard calibration={info.calibration} />}
      <SavedTemplatesPanel />
      <StarterTemplatesPanel />
      <TemplateImportWizard />
    </Page>
  );
}

/**
 * One labelled metadata cell in the current-template summary grid.
 */
function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line/80 bg-paper/40 px-3 py-2">
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-ink">{value}</dd>
    </div>
  );
}
