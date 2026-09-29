// LinkedIn/Indeed access, granted at runtime (optional_host_permissions). With it, a
// content script shows the page chip and completes saved cards as the user browses.
// It never clicks, scrolls, navigates or fetches pages by itself.

export const BOARD_ORIGINS = ["https://www.linkedin.com/*", "https://*.indeed.com/*"];
const SCRIPT_ID = "resumetailor-boards";
const MATCHES = ["https://www.linkedin.com/jobs/*", "https://*.indeed.com/*"];
export const CONTENT_FILES = ["lib/sites.js", "content.js"];

export async function hasBoardAccess() {
  return chrome.permissions.contains({ origins: BOARD_ORIGINS });
}

// Must run in a user gesture (a popup or options click).
export async function requestBoardAccess() {
  const granted = await chrome.permissions.request({ origins: BOARD_ORIGINS });
  if (granted) await syncBoardScripts();
  return granted;
}

// Register the content script when access is granted; unregister when it is removed.
export async function syncBoardScripts() {
  const granted = await hasBoardAccess();
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [SCRIPT_ID] });
  if (granted && !existing.length) {
    await chrome.scripting.registerContentScripts([{
      id: SCRIPT_ID,
      matches: MATCHES,
      js: CONTENT_FILES,
      runAt: "document_idle",
      persistAcrossSessions: true,
    }]);
  } else if (!granted && existing.length) {
    await chrome.scripting.unregisterContentScripts({ ids: [SCRIPT_ID] });
  }
  return granted;
}
