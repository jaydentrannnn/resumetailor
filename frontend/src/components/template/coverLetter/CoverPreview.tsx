import type { CoverLetterSettings } from "../../../api";
import { useCoverPreview } from "../../../lib/useCoverPreview";

/**
 * Page one of a sample letter under the draft settings, as an image — a second PDF
 * frame would fight the Template page's own preview for the browser's PDF plugin.
 */
export function CoverPreview({ settings }: { settings: CoverLetterSettings }) {
  const { url, loading, error } = useCoverPreview(settings);
  return (
    <section className="border-t border-line pt-4" aria-labelledby="cover-preview">
      <div className="flex items-center justify-between gap-3">
        <h3 id="cover-preview" className="font-semibold">
          Preview
        </h3>
        <span role="status" className="text-xs text-ink-muted">
          {loading ? "Updating…" : ""}
        </span>
      </div>
      <p className="mt-1 text-xs text-ink-muted">
        Sample body text; your letters are written for each job.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      ) : url ? (
        <img
          src={url}
          alt="Cover letter preview"
          className={`mt-3 w-full rounded-sm border border-line bg-doc-preview transition-opacity ${loading ? "opacity-60" : ""}`}
        />
      ) : (
        <div className="mt-3 aspect-[8.5/11] w-full animate-pulse rounded-sm border border-line bg-sunken" />
      )}
    </section>
  );
}
