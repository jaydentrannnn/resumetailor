import { capture, lookup } from "./api.js";

//: Classic scripts injected in order; the last one's completion value is the result.
export const EXTRACT_FILES = ["lib/sites.js", "lib/applyLink.js", "extract.js"];
const LIB_FILES = ["lib/sites.js", "lib/applyLink.js"];

function httpTab(tab, message) {
  if (!tab?.id || !/^https?:\/\//.test(tab.url || "")) throw new Error(message);
}

export async function extractTab(tabId) {
  const frames = await chrome.scripting.executeScript({ target: { tabId }, files: EXTRACT_FILES });
  const result = frames[0]?.result;
  if (!result?.url) throw new Error("This page cannot be read. Open a job posting and try again.");
  return result;
}

// Extract the page and send it. ``data`` may be passed when it was already extracted.
export async function captureTab(tab, selectionText = "", data = null) {
  httpTab(tab, "Open an HTTP job posting to capture it.");
  if (!data) {
    try {
      data = await extractTab(tab.id);
    } catch (error) {
      if (!selectionText) throw error;
      data = {
        url: tab.url, final_url: tab.url, apply_url: "", company: "", role: tab.title || "",
        location: "", jd_text: "", ats_guess: "", apply_kind: "unknown",
      };
    }
  }
  if (selectionText) data.jd_text = selectionText;
  if (data.jd_text.length > 200_000) {
    throw new Error("This description is too long to send. Select only the job description and use Send selection.");
  }
  // Navigation during injection must not silently capture a different page.
  if (new URL(data.url).href !== new URL(tab.url).href) {
    throw new Error("The page changed while capturing. Try again.");
  }
  const result = await capture(data);
  return { result, data };
}

async function inTab(tabId, func) {
  await chrome.scripting.executeScript({ target: { tabId }, files: LIB_FILES });
  const [frame] = await chrome.scripting.executeScript({ target: { tabId }, func });
  return frame?.result ?? null;
}

// What the page is (board job, search page, other) and its apply link, both read from
// the open job's detail container only (lib/applyLink.js).
export async function pageFacts(tab) {
  try {
    return await inTab(tab.id, () => {
      const sites = globalThis.RTSites;
      const site = sites.siteOf(location.href);
      const job = sites.jobFromUrl(location.href);
      return {
        site,
        job_key: job?.key || "",
        apply_url: globalThis.RTApplyLink.findApplyLink(document, { site, baseUrl: location.href }),
        apply_kind: site ? sites.applyKind(document, site) : "unknown",
        card_count: site ? sites.readCards(document, location.href).length : 0,
      };
    });
  } catch {
    return null; // a protected page (store, settings) can still be looked up by URL
  }
}

export async function lookupTab(tab) {
  httpTab(tab, "Open an HTTP job posting first.");
  const data = await pageFacts(tab);
  let found = await lookup(tab.url);
  if (!found.application && data?.apply_url) found = await lookup(data.apply_url);
  return { lookup: found, data };
}

export async function readTabCards(tab) {
  httpTab(tab, "Open a LinkedIn or Indeed search page first.");
  const cards = await inTab(tab.id, () => globalThis.RTSites.readCards(document, location.href));
  return cards || [];
}
