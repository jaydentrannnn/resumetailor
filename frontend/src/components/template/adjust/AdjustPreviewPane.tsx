/**
 * The resume under the draft adjustments, one image per page, refreshed a moment after
 * each change. Images, not the PDF frame: they swap without a flash and never fight the
 * browser's single PDF viewer. The old pages stay (dimmed) until the new ones arrive.
 */
export function AdjustPreviewPane({
  pages,
  loading,
  error,
}: {
  pages: string[];
  loading: boolean;
  error: string | null;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-3 pb-2">
        <span className="text-xs text-ink-muted">
          Draft, not saved
          {pages.length > 1 && <span className="font-mono"> · {pages.length} pages</span>}
        </span>
        <span role="status" className="shrink-0 text-xs text-ink-muted">
          {loading ? "Updating…" : ""}
        </span>
      </div>
      {error && (
        <p role="alert" className="pb-2 text-sm text-danger">
          {error}
        </p>
      )}
      {pages.length ? (
        <div className="space-y-3">
          {pages.map((src, i) => (
            <img
              key={src}
              src={src}
              alt={pages.length > 1 ? `Draft page ${i + 1}` : "Draft preview"}
              className={`w-full rounded-sm border border-line bg-doc-preview transition-opacity ${loading ? "opacity-60" : ""}`}
            />
          ))}
        </div>
      ) : (
        !error && (
          <div className="aspect-[8.5/11] w-full animate-pulse rounded-sm border border-line bg-sunken" />
        )
      )}
    </div>
  );
}
