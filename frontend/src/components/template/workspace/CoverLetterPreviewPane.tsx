import type { CoverLetterSettings } from "../../../api";
import { useCoverPreview } from "../../../lib/useCoverPreview";

/**
 * Page one of a sample letter under the current settings, as an image. It follows every
 * change (debounced; the latest request wins), so the controls beside it read as live.
 */
export function CoverLetterPreviewPane({ settings }: { settings: CoverLetterSettings }) {
  const { url, loading, error } = useCoverPreview(settings);
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-3 pb-2">
        <span className="text-xs text-ink-muted">
          Sample body text; your letters are written for each job.
        </span>
        <span role="status" className="shrink-0 text-xs text-ink-muted">
          {loading ? "Updating…" : ""}
        </span>
      </div>
      {error ? (
        <p role="alert" className="p-5 text-sm text-danger">
          {error}
        </p>
      ) : url ? (
        <img
          src={url}
          alt="Cover letter preview"
          className={`w-full rounded-sm border border-line bg-doc-preview transition-opacity ${loading ? "opacity-60" : ""}`}
        />
      ) : (
        <div className="aspect-[8.5/11] w-full animate-pulse rounded-sm border border-line bg-sunken" />
      )}
    </div>
  );
}
