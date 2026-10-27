/** Dispatched on `window` after the applicant settles an application, so a tab-close
 * countdown that just started shows at once rather than at the next idle poll
 * (`components/shell/TabCloseNotice`). */
export const TABS_CHANGED_EVENT = "rt:tabs-changed";

export function announceTabsChanged(): void {
  window.dispatchEvent(new Event(TABS_CHANGED_EVENT));
}
