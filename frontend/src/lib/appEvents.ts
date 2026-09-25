/**
 * App-wide "something changed, reload" signals between providers that don't share
 * state (the setup pill, the Tailor page's config, the template page). A window event
 * keeps them decoupled; each listener refetches from the server, which stays the
 * source of truth.
 */
export type AppEvent =
  /** Model settings, a key, or the template changed: the setup checklist is stale. */
  | "rt:setup-changed"
  /** The active template changed: page-fit numbers and previews are stale. */
  | "rt:template-changed";

export function emitAppEvent(name: AppEvent): void {
  window.dispatchEvent(new Event(name));
}

/** Subscribe; returns the unsubscribe function (for a `useEffect` cleanup). */
export function onAppEvent(name: AppEvent, handler: () => void): () => void {
  window.addEventListener(name, handler);
  return () => window.removeEventListener(name, handler);
}
