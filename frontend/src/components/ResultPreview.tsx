import { previewUrl } from "../api";

/**
 * Inline PDF preview of the finished tailored resume, at the bottom of the Tailor
 * page. The tailored PDF also auto-downloads (see `runState.tsx`); this lets the
 * user actually look at it without leaving the browser or opening the download.
 * Keying the iframe on `jobId` busts the cache automatically — unlike the Template
 * tab's preview, which reuses one URL across rebuilds, every job has a fresh id.
 */
export function ResultPreview({ jobId }: { jobId: string }) {
  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <h2 className="font-display text-xl font-semibold">Tailored resume</h2>
      <div className="mt-4 overflow-hidden rounded-lg border border-line bg-paper/40">
        <iframe
          key={jobId}
          title="Tailored resume preview"
          src={previewUrl(jobId)}
          className="h-[70vh] w-full bg-white"
        />
      </div>
    </section>
  );
}
