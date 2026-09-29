// Find a job's apply link inside its detail container (classic script: injected before
// extract.js and the page content script, and imported for side effects by node tests).
// Never "the first link on the page that says Apply": a search page lists many jobs, and
// the nav bar, footer and sidebar all carry their own "apply" links.
(function (root) {
  const BOARD_HOSTS = ["linkedin.com", "indeed.com"];
  const APPLY_TEXT = /\bapply\b/i;
  const NOT_APPLY = /privacy|policy|terms|applied|how to apply|save|similar|filter/i;

  function hostIs(host, part) {
    return host === part || host.endsWith(`.${part}`);
  }

  function isVisible(element) {
    if (!element || element.closest("script,style,[hidden],[aria-hidden='true']")) return false;
    if (typeof root.getComputedStyle !== "function") return true;
    const style = root.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  }

  function label(element) {
    return [element.getAttribute("aria-label"), element.textContent]
      .filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  }

  // An absolute http(s) URL for ``href``, with LinkedIn's outbound redirect unwrapped. A
  // link back into the job board itself is not an apply URL ("" is returned): it keys to
  // the same posting, and following Indeed's /applystart would need a server fetch.
  function unwrap(href, base) {
    if (!href) return "";
    let url;
    try {
      url = new URL(href, base);
    } catch {
      return "";
    }
    const host = url.hostname.toLowerCase();
    if (hostIs(host, "linkedin.com") && /\/(redir\/redirect|safety\/go)/.test(url.pathname)) {
      const nested = url.searchParams.get("url");
      if (!nested) return "";
      try {
        url = new URL(nested);
      } catch {
        return "";
      }
    }
    if (!["http:", "https:"].includes(url.protocol)) return "";
    const final = url.hostname.toLowerCase();
    if (BOARD_HOSTS.some((part) => hostIs(final, part))) return "";
    return url.href;
  }

  // The element that holds the job's own details, or null when there is none to scope to.
  function scope(doc, site) {
    const sites = root.RTSites;
    if (sites && site) return sites.detailContainer(doc, site);
    return doc.querySelector("main,[role='main'],article") || doc.body;
  }

  function findApplyLink(doc, { site = "", baseUrl = "" } = {}) {
    const container = scope(doc, site);
    if (!container) return "";
    const base = baseUrl || doc.location?.href || "";
    const preferred = root.RTSites && site ? root.RTSites.applyLinkSelectors(site) : [];
    for (const selector of preferred) {
      for (const anchor of container.querySelectorAll(selector)) {
        const url = unwrap(anchor.getAttribute("href"), base);
        if (url && isVisible(anchor)) return url;
      }
    }
    for (const anchor of container.querySelectorAll("a[href]")) {
      if (anchor.closest("nav,header,footer")) continue;
      const text = label(anchor);
      if (!APPLY_TEXT.test(text) || NOT_APPLY.test(text) || !isVisible(anchor)) continue;
      const url = unwrap(anchor.getAttribute("href"), base);
      if (url) return url;
    }
    return "";
  }

  root.RTApplyLink = { findApplyLink, unwrap };
})(globalThis);
