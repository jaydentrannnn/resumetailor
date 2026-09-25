import { capture, lookup } from "./api.js";

export async function extractTab(tabId) {
  const frames = await chrome.scripting.executeScript({ target: { tabId }, files: ["extract.js"] });
  const result = frames[0]?.result;
  if (!result?.url) throw new Error("This page cannot be read. Open a job posting and try again.");
  return result;
}

export async function captureTab(tab, selectionText = "") {
  if (!tab?.id || !/^https?:\/\//.test(tab.url || "")) {
    throw new Error("Open an HTTP job posting to capture it.");
  }
  let data;
  try {
    data = await extractTab(tab.id);
  } catch (error) {
    if (!selectionText) throw error;
    data = {
      url: tab.url, final_url: tab.url, apply_url: "", company: "", role: tab.title || "",
      location: "", jd_text: "", ats_guess: "",
    };
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

export async function lookupTab(tab) {
  if (!tab?.id || !/^https?:\/\//.test(tab.url || "")) {
    throw new Error("Open an HTTP job posting first.");
  }
  let data = null;
  try {
    const [frame] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const link = [...document.querySelectorAll("a[href]")].find((item) =>
          /\bapply\b/i.test(item.textContent || ""),
        );
        if (!link) return { apply_url: "" };
        try {
          const url = new URL(link.getAttribute("href"), location.href);
          const nested = location.hostname.includes("linkedin.com") && url.pathname.includes("/redir/redirect")
            ? url.searchParams.get("url") : null;
          const result = nested ? new URL(nested) : url;
          return { apply_url: ["http:", "https:"].includes(result.protocol) ? result.href : "" };
        } catch {
          return { apply_url: "" };
        }
      },
    });
    data = frame?.result || null;
  } catch {
    // Lookup can still use the URL of a protected page.
  }
  let found = await lookup(tab.url);
  if (!found.application && data?.apply_url) found = await lookup(data.apply_url);
  return { lookup: found, data };
}
