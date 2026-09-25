import { useEffect, useRef, useState } from "react";

/**
 * Copy `text` to the clipboard, with a hidden-textarea fallback for non-secure contexts.
 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.left = "-9999px";
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand("copy");
  } finally {
    document.body.removeChild(area);
  }
}

export function CopyButton({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, []);

  async function onCopy() {
    /** Copy `text` and briefly confirm success on the button. */
    const ok = await copyText(text);
    if (!ok) return;
    if (timerRef.current) window.clearTimeout(timerRef.current);
    setCopied(true);
    timerRef.current = window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => void onCopy()}
      className="inline-grid shrink-0 place-items-center whitespace-nowrap rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink-muted hover:border-accent hover:text-accent"
    >
      {/* Both labels occupy the same grid cell so the track sizes to the wider of
          the two — visibility, not display, so the button never reflows its
          neighbours when the label swaps. */}
      <span className={`col-start-1 row-start-1 ${copied ? "invisible" : ""}`} aria-hidden>
        {label}
      </span>
      <span className={`col-start-1 row-start-1 ${copied ? "" : "invisible"}`} aria-hidden>
        Copied
      </span>
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </button>
  );
}
