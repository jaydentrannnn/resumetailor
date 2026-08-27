import { previewUrl } from "../api";

/**
 * Inline PDF preview of the finished tailored resume, at the bottom of the Tailor
 * page. The tailored PDF also auto-downloads (see `runState.tsx`); this lets the
 * user actually look at it without leaving the browser or opening the download.
 * Keying the iframe on `jobId` busts the cache automatically — unlike the Template
 * tab's preview, which reuses one URL across rebuilds, every job has a fresh id.
 */
export function ResultPreview({ jobId }: { jobId: string }) {
  const src = previewUrl(jobId);
  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-xl font-semibold">Tailored resume</h2>
        <a
          href={src}
          target="_blank"
          rel="noreferrer"
          className="text-sm text-ink-muted underline-offset-2 hover:text-accent hover:underline"
        >
          Open in new tab
        </a>
      </div>
      <div className="mt-4 overflow-hidden rounded-lg border border-line bg-paper/40">
        <iframe
          key={jobId}
          title="Tailored resume preview"
          src={src}
          className="h-[70vh] w-full bg-white"
        >
          <p className="p-4 text-sm text-ink-muted">
            PDF preview is not available in this browser.{" "}
            <a href={src} target="_blank" rel="noreferrer" className="text-accent underline">
              Open the PDF in a new tab
            </a>
            .
          </p>
        </iframe>
      </div>
    </section>
  );
}
