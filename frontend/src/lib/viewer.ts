/** A document pane beside a page's controls fills the window below the bars. */
export const VIEWER_HEIGHT = "h-(--rt-viewer-h)";

/**
 * Grid columns for controls beside a document: the document column is one page wide at
 * the window's height (`--rt-doc-w`, never more than 62% of the row) and the controls
 * take the rest, so widening the window gives the controls the room.
 */
export const BESIDE_DOCUMENT = "lg:grid-cols-[minmax(24rem,1fr)_min(var(--rt-doc-w),62%)]";
export const DOCUMENT_FIRST = "lg:grid-cols-[min(var(--rt-doc-w),62%)_minmax(24rem,1fr)]";

/**
 * The embedded PDF, framed to the page width. Chromium's PDF viewer (Chrome, Edge,
 * WebView2) reads this from the URL fragment; `toolbar=0&navpanes=0` hides its own
 * chrome inside the app. Ctrl+wheel still zooms inside the frame.
 */
export function viewerSrc(src: string): string {
  return `${src}#toolbar=0&navpanes=0&view=FitH`;
}
