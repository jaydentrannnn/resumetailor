import { useEffect, useRef, useState } from "react";

import { fetchTemplateDraftPreview, fetchTemplateSourcePreview } from "../../api";

type Props = {
  sourceSha256: string;
  profile: Record<string, unknown> | null;
};

/**
 * Side-by-side comparison: the original upload as-is, and what installing the current
 * draft profile would produce.
 *
 * The source preview loads automatically (one conversion, keyed by upload sha). The
 * draft preview is manual — building + rendering a staged profile takes several
 * seconds under Word, and the profile changes on nearly every keystroke while mapping,
 * so auto-regenerating on each edit would mean a near-constant spinner. The user
 * reviews their changes, then asks for a fresh draft render when ready to check them.
 */
export function PreviewCompare({ sourceSha256, profile }: Props) {
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);

  const [draftUrl, setDraftUrl] = useState<string | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftStale, setDraftStale] = useState(false);

  const sourceUrlRef = useRef<string | null>(null);
  const draftUrlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSourceLoading(true);
    setSourceError(null);
    void fetchTemplateSourcePreview(sourceSha256)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        if (sourceUrlRef.current) URL.revokeObjectURL(sourceUrlRef.current);
        sourceUrlRef.current = url;
        setSourceUrl(url);
      })
      .catch((err) => {
        if (!cancelled) setSourceError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setSourceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceSha256]);

  // Any profile edit invalidates the last-rendered draft without refetching it —
  // regenerating is the explicit "Generate draft preview" action below.
  useEffect(() => {
    setDraftStale(true);
  }, [profile]);

  useEffect(
    () => () => {
      if (sourceUrlRef.current) URL.revokeObjectURL(sourceUrlRef.current);
      if (draftUrlRef.current) URL.revokeObjectURL(draftUrlRef.current);
    },
    [],
  );

  const generateDraft = () => {
    if (!profile) return;
    setDraftLoading(true);
    setDraftError(null);
    void fetchTemplateDraftPreview(sourceSha256, profile)
      .then((url) => {
        if (draftUrlRef.current) URL.revokeObjectURL(draftUrlRef.current);
        draftUrlRef.current = url;
        setDraftUrl(url);
        setDraftStale(false);
      })
      .catch((err) => {
        setDraftError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setDraftLoading(false);
      });
  };

  return (
    <div className="mt-4 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
          Preview: original vs. draft
        </p>
        <button
          type="button"
          disabled={!profile || draftLoading}
          onClick={generateDraft}
          className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
        >
          {draftLoading
            ? "Rendering draft…"
            : draftUrl
              ? "Refresh draft preview"
              : "Generate draft preview"}
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="overflow-hidden rounded-lg border border-line/80 bg-paper/40">
          <p className="border-b border-line/80 bg-paper/60 px-3 py-1.5 text-xs font-medium text-ink-muted">
            Original upload
          </p>
          {sourceLoading ? (
            <p className="p-3 text-xs text-ink-muted">Converting…</p>
          ) : sourceError ? (
            <p className="p-3 text-xs text-danger">{sourceError}</p>
          ) : sourceUrl ? (
            <iframe title="Original upload preview" src={sourceUrl} className="h-[55vh] w-full bg-white" />
          ) : null}
        </div>

        <div className="overflow-hidden rounded-lg border border-line/80 bg-paper/40">
          <p className="flex items-center justify-between border-b border-line/80 bg-paper/60 px-3 py-1.5 text-xs font-medium text-ink-muted">
            <span>Draft with this mapping</span>
            {draftUrl && draftStale ? (
              <span className="text-warn">Mapping changed — refresh to update</span>
            ) : null}
          </p>
          {draftError ? (
            <p className="p-3 text-xs text-danger">{draftError}</p>
          ) : draftUrl ? (
            <iframe
              title="Draft mapping preview"
              src={draftUrl}
              className={`h-[55vh] w-full bg-white ${draftStale ? "opacity-60" : ""}`}
            />
          ) : (
            <p className="p-3 text-xs text-ink-muted">
              Not generated yet — click “Generate draft preview” above.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
