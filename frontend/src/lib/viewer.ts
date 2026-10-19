/**
 * How the document viewer frames a PDF: fit its width, fit a whole page, or a zoom
 * percentage. Chromium's PDF viewer (Chrome, Edge, WebView2) reads these from the URL
 * fragment; `toolbar=0&navpanes=0` hides its own chrome inside the app.
 */
export type ViewerFit = "width" | "page" | number;

/** A document pane beside a page's controls fills the window below the bars. */
export const VIEWER_HEIGHT =
  "h-[calc(100vh-var(--rt-bar-top)-var(--rt-bar-bottom)-5.5rem)] min-h-[28rem]";

export const ZOOM_STEPS = [50, 67, 75, 90, 100, 110, 125, 150, 175, 200];

export function viewerSrc(src: string, fit: ViewerFit): string {
  const view = fit === "width" ? "view=FitH" : fit === "page" ? "view=Fit" : `zoom=${fit}`;
  return `${src}#toolbar=0&navpanes=0&${view}`;
}

/** The next zoom step in `direction` from the current framing (fits start at 100%). */
export function stepZoom(fit: ViewerFit, direction: 1 | -1): number {
  const current = typeof fit === "number" ? fit : 100;
  const next =
    direction > 0
      ? ZOOM_STEPS.find((step) => step > current)
      : [...ZOOM_STEPS].reverse().find((step) => step < current);
  return next ?? current;
}
