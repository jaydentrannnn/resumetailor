import { Button } from "../ui";
import { useEffect, useState } from "react";
import { templatePreviewUrl } from "../../api";
import { usePrintTarget } from "../../lib/printTarget";
import { OpenDocumentLink } from "../FileActions";

/** Fetch the exact revision before mounting a PDF; late responses cannot replace it. */
export function TemplatePreview({
  revision,
  pending,
  refreshKey,
  activeLabel,
}: {
  revision: string | null;
  pending: string | null;
  refreshKey: number;
  activeLabel?: string | null;
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
  usePrintTarget(!pending && pdf?.revision === revision ? pdf.url : null);

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
        <Button variant="ghost" size="sm" className="mt-2" onClick={() => setRetry((r) => r + 1)}>
          Retry preview
        </Button>
      </div>
    );
  if (!revision || !pdf || pdf.revision !== revision)
    return (
      <p role="status" className="p-5 text-sm text-ink-muted">
        Loading template preview…
      </p>
    );
  return (
    <div className="min-w-0 overflow-hidden rounded-sm">
      <div className="flex items-center justify-between gap-3 pb-2">
        <span className="text-xs text-ink-muted">Active: {activeLabel || "Current template"}</span>
        <OpenDocumentLink href={pdf.url} className="rt-link text-xs" />
      </div>
      <iframe
        key={pdf.url}
        title="Template preview"
        src={`${pdf.url}#toolbar=0&navpanes=0&view=FitH`}
        className="aspect-[8.5/11] w-full rounded-sm border border-line bg-doc-preview"
      />
    </div>
  );
}
