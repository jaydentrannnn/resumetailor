import { useEffect, useState } from "react";
import { adjustPreviewPageUrl, fetchAdjustPreview, type TemplateAdjustments } from "../api";
import { ApiError, describe } from "./errors";

/**
 * Page images of the resume under the draft adjustments (nothing installed). Debounced,
 * and the latest draft wins: an older request is aborted here, and the server drops one
 * a newer request superseded (409), which is not an error. `null` adjustments wait.
 */
export function useAdjustPreview(adj: TemplateAdjustments | null, delayMs = 600) {
  const [pages, setPages] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = adj ? JSON.stringify(adj) : null;

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      fetchAdjustPreview(JSON.parse(key) as TemplateAdjustments, controller.signal)
        .then((res) => {
          const urls = Array.from({ length: res.pages }, (_, i) =>
            adjustPreviewPageUrl(res.key, i + 1),
          );
          setPages(urls);
          setError(null);
          setLoading(false);
        })
        .catch((reason) => {
          if (controller.signal.aborted) return;
          if (reason instanceof ApiError && reason.status === 409) return;
          setError(describe(reason).detail);
          setLoading(false);
        });
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [key, delayMs]);

  return { pages, loading, error };
}
