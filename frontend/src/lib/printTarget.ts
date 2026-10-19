import { useEffect } from "react";

/**
 * Ctrl/Cmd+P prints the document on screen (the tailored resume, the cover letter, the
 * template preview) rather than the page around it. Viewers register their PDF URL
 * while they show it; the newest registration wins.
 */
const targets: string[] = [];

export function registerPrintTarget(url: string): () => void {
  targets.push(url);
  return () => {
    const index = targets.lastIndexOf(url);
    if (index >= 0) targets.splice(index, 1);
  };
}

export function currentPrintTarget(): string | null {
  return targets.at(-1) ?? null;
}

/** Register `url` as the printable document while the calling component shows it. */
export function usePrintTarget(url: string | null): void {
  useEffect(() => (url ? registerPrintTarget(url) : undefined), [url]);
}

const FRAME_ID = "rt-print-frame";

/**
 * Print a same-origin PDF through an off-screen frame. The frame stays until the next
 * print: removing it while the print dialog is open cancels the dialog.
 */
export function printDocument(url: string): void {
  document.getElementById(FRAME_ID)?.remove();
  const frame = document.createElement("iframe");
  frame.id = FRAME_ID;
  frame.title = "Print";
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  frame.addEventListener("load", () => frame.contentWindow?.print(), { once: true });
  frame.src = url;
  document.body.appendChild(frame);
}
