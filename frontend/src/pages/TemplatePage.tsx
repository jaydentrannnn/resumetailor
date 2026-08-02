import { useCallback, useRef, useState, type DragEvent } from "react";
import { templatePreviewUrl } from "../api";
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
 * Template tab: preview the current tagged template and upload a new Google Docs export.
 */
export function TemplatePage() {
  const {
    info,
    loading,
    uploading,
    error,
    buildLog,
    lastBuildOk,
    previewKey,
    refresh,
    upload,
  } = useTemplateState();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const onFile = useCallback(
    (file: File | null) => {
      /** Hand a chosen .docx to the upload pipeline. */
      if (!file) return;
      void upload(file);
    },
    [upload],
  );

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      /** Accept a dropped .docx from the drag target. */
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files?.[0] ?? null;
      onFile(file);
    },
    [onFile],
  );

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-semibold">Current template</h2>
            <p className="mt-1 text-sm text-ink-muted">
              Tagged template filled with your full master resume. Formatting comes from
              your Google Docs export; only the words change when you tailor.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading || uploading}
            className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
          >
            Refresh
          </button>
        </div>

        {loading && !info ? (
          <p className="mt-4 text-sm text-ink-muted">Loading template info…</p>
        ) : info ? (
          <>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
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
                label="Fit constants"
                value={`${info.calibration.chars_per_line} chars/line · ${info.calibration.lines_per_page} lines/page`}
              />
            </dl>

            {info.calibration.stale && info.calibration.message ? (
              <p className="mt-4 rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
                {info.calibration.message}
              </p>
            ) : null}

            {info.tagged.exists ? (
              <div className="mt-4 overflow-hidden rounded-lg border border-line bg-paper/40">
                <iframe
                  key={previewKey}
                  title="Template preview"
                  src={`${templatePreviewUrl()}?v=${previewKey}`}
                  className="h-[70vh] w-full bg-white"
                />
              </div>
            ) : (
              <p className="mt-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                No tagged template on disk. Upload a Google Docs .docx export below to
                generate one.
              </p>
            )}
          </>
        ) : null}
      </section>

      <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
        <h2 className="font-display text-xl font-semibold">Replace template</h2>
        <p className="mt-1 text-sm text-ink-muted">
          Upload a fresh Google Docs export (File → Download → Microsoft Word). This
          overwrites{" "}
          <code className="rounded bg-paper px-1 text-xs">templates/original_export.docx</code>{" "}
          and regenerates the tagged template. A timestamped backup of the previous
          baseline is kept under{" "}
          <code className="rounded bg-paper px-1 text-xs">templates/backups/</code>.
        </p>

        <div
          onDragEnter={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`mt-4 flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 transition ${
            dragging
              ? "border-accent bg-accent-soft/60"
              : "border-line bg-paper/40 hover:border-accent/60"
          }`}
        >
          <p className="text-sm text-ink-muted">
            {uploading ? "Uploading and rebuilding…" : "Drop a .docx here, or"}
          </p>
          <button
            type="button"
            disabled={uploading}
            onClick={() => inputRef.current?.click()}
            className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {uploading ? "Working…" : "Choose file"}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            className="hidden"
            onChange={(e) => {
              onFile(e.target.files?.[0] ?? null);
              e.target.value = "";
            }}
          />
        </div>

        {error && lastBuildOk === false ? (
          <p className="mt-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {error.split("\n")[0]}
          </p>
        ) : null}

        {lastBuildOk === true ? (
          <p className="mt-4 rounded-md bg-accent-soft px-3 py-2 text-sm text-accent">
            Template rebuilt successfully.
            {info?.calibration.stale
              ? " Fit constants may be stale — run calibrate.py and restart the server."
              : null}
          </p>
        ) : null}

        {buildLog ? (
          <pre className="mt-4 max-h-48 overflow-auto rounded-md border border-line bg-paper/60 p-3 text-xs text-ink whitespace-pre-wrap">
            {buildLog}
          </pre>
        ) : null}
      </section>
    </div>
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
