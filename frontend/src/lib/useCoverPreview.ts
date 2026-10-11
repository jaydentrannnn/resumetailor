import { useEffect, useRef, useState } from "react";
import { type CoverLetterSettings, fetchCoverLetterPreview } from "../api";
import { describe } from "./errors";

/** Debounced preview image of a sample letter under `settings`; the latest request wins. */
export function useCoverPreview(settings: CoverLetterSettings | null, delayMs = 700) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<string | null>(null);
  const key = settings ? JSON.stringify(settings) : null;

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      fetchCoverLetterPreview(JSON.parse(key) as CoverLetterSettings, controller.signal)
        .then((blob) => {
          if (current.current) URL.revokeObjectURL(current.current);
          current.current = URL.createObjectURL(blob);
          setUrl(current.current);
          setError(null);
          setLoading(false);
        })
        .catch((reason) => {
          if (controller.signal.aborted) return;
          setError(describe(reason).detail);
          setLoading(false);
        });
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [key, delayMs]);

  useEffect(
    () => () => {
      if (current.current) URL.revokeObjectURL(current.current);
    },
    [],
  );
  return { url, loading, error };
}
