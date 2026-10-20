/** A document pane beside a page's controls fills the window below the bars. */
export const VIEWER_HEIGHT = "h-(--rt-viewer-h)";

/**
 * Grid columns for controls beside a document: 6:4, so widening the window grows both
 * the controls and the page.
 */
export const BESIDE_DOCUMENT = "lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]";

/**
 * The embedded PDF, framed to the page width. Chromium's PDF viewer (Chrome, Edge,
 * WebView2) reads this from the URL fragment; `toolbar=0&navpanes=0` hides its own
 * chrome inside the app. Ctrl+wheel still zooms inside the frame.
 */
export function viewerSrc(src: string): string {
  return `${src}#toolbar=0&navpanes=0&view=FitH`;
}
