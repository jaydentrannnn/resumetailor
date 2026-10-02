import { useEffect, useState } from "react";
import { templatePreviewUrl } from "../../api";

/** Fetch the exact revision before mounting a PDF; late responses cannot replace it. */
export function TemplatePreview({
  revision,
  pending,
  refreshKey,
}: {
  revision: string | null;
  pending: string | null;
  refreshKey: number;
}) {
  const [pdf, setPdf] = useState<{ revision: string; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!revision || pending) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setPdf(null);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(
          `${templatePreviewUrl()}?revision=${encodeURIComponent(revision)}`,
          { signal: controller.signal },
        );
        if (!response.ok) {
          let message = `Preview could not load (${response.status})`;
          try {
            message = (await response.json()).detail ?? message;
          } catch {
            /* no body */
          }
          throw new Error(message);
        }
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setPdf({ revision, url: objectUrl });
      } catch (err) {
        if (!controller.signal.aborted) setError(String(err));
      }
    })();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [revision, pending, retry, refreshKey]);

  if (pending)
    return (
      <p role="status" className="p-5 text-sm text-ink-muted">
        Switching to {pending}…
      </p>
    );
  if (error)
    return (
      <div role="alert" className="p-5 text-sm text-danger">
        <p>{error}</p>
        <button className="mt-2 underline" onClick={() => setRetry((r) => r + 1)}>
          Retry preview
        </button>
      </div>
    );
  if (!revision || !pdf || pdf.revision !== revision)
    return (
      <p role="status" className="p-5 text-sm text-ink-muted">
        Loading template preview…
      </p>
    );
  return (
    <div className="order-1 mt-4 overflow-hidden rounded-lg border border-line bg-paper/40">
      <div className="flex justify-end border-b border-line px-3 py-1.5">
        <a
          href={pdf.url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-ink-muted underline"
        >
          Open in new tab
        </a>
      </div>
      <iframe
        key={pdf.url}
        title="Template preview"
        src={`${pdf.url}#toolbar=0&navpanes=0`}
        className="h-[70vh] w-full bg-doc-preview"
      />
    </div>
  );
}
