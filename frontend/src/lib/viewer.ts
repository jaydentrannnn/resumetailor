/**
 * A document pane beside a page's controls: Letter aspect, capped at the window
 * height so a narrow column does not leave empty space under the page.
 */
export const VIEWER_HEIGHT = "aspect-[8.5/11] max-h-(--rt-viewer-h) w-full";

/**
 * Grid columns for controls beside a document: half and half, so widening the window
 * grows both the controls and the page.
 */
export const BESIDE_DOCUMENT = "lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]";

/**
 * The embedded PDF, framed to the page width. Chromium's PDF viewer (Chrome, Edge,
 * WebView2) reads this from the URL fragment; `toolbar=0&navpanes=0` hides its own
 * chrome inside the app. Ctrl+wheel still zooms inside the frame.
 */
export function viewerSrc(src: string): string {
  return `${src}#toolbar=0&navpanes=0&view=FitH`;
}
