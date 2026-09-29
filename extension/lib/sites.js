// Every LinkedIn/Indeed selector the extension uses, in one place (classic script:
// injected before extract.js and the page content script; node tests import it for its
// side effect). Each list is tried in order, so when a site changes its markup a new
// selector goes first and the old ones stay as fallbacks.
(function (root) {
  const SELECTORS = {
    linkedin: {
      // Search/collections result cards. LinkedIn virtualises the list: a card scrolled
      // out of view keeps only its id, so cards without a title are skipped.
      cards: [
        "li[data-occludable-job-id]",
        "[data-job-id]",
        ".job-card-container",
        ".base-card[data-entity-urn]",
        ".job-search-card",
      ],
      cardTitle: [
        ".job-card-list__title--link",
        ".job-card-list__title",
        ".job-card-container__link",
        ".artdeco-entity-lockup__title",
        ".base-search-card__title",
        "h3",
      ],
      cardCompany: [
        ".artdeco-entity-lockup__subtitle",
        ".job-card-container__primary-description",
        ".job-card-container__company-name",
        ".base-search-card__subtitle",
        "h4",
      ],
      cardLocation: [
        ".job-card-container__metadata-wrapper li",
        ".job-card-container__metadata-item",
        ".artdeco-entity-lockup__caption",
        ".job-search-card__location",
      ],
      // The pane (search page) or page (job view) that shows one job's details.
      detail: [
        ".jobs-search__job-details--container",
        ".jobs-search__job-details",
        ".job-view-layout",
        ".jobs-details",
        ".scaffold-layout__detail",
        ".top-card-layout",
      ],
      description: [
        ".jobs-description__content",
        ".jobs-description-content__text",
        ".jobs-description",
        "#job-details",
        ".show-more-less-html__markup",
        ".description__text",
      ],
      role: [
        ".job-details-jobs-unified-top-card__job-title",
        ".jobs-unified-top-card__job-title",
        ".top-card-layout__title",
        "h1",
        "h2",
      ],
      company: [
        ".job-details-jobs-unified-top-card__company-name",
        ".jobs-unified-top-card__company-name",
        ".topcard__org-name-link",
        ".top-card-layout__second-subline a",
      ],
      location: [
        ".job-details-jobs-unified-top-card__tertiary-description-container",
        ".job-details-jobs-unified-top-card__primary-description-container",
        ".jobs-unified-top-card__bullet",
        ".topcard__flavor--bullet",
      ],
      applyButtons: [
        ".jobs-apply-button",
        ".jobs-s-apply button",
        "button[aria-label*='Apply']",
        "a[aria-label*='Apply']",
        ".apply-button",
      ],
      applyLinks: ["a.jobs-apply-button", "a[href*='/redir/redirect']", ".jobs-s-apply a", "a.apply-button"],
    },
    indeed: {
      cards: ["a[data-jk]", "[data-jk]"],
      cardRoot: [".job_seen_beacon", ".cardOutline", "li", "td.resultContent"],
      cardTitle: ["h2.jobTitle span[title]", "h2.jobTitle", "a.jcs-JobTitle", "a[data-jk]"],
      cardCompany: ["[data-testid='company-name']", ".companyName"],
      cardLocation: ["[data-testid='text-location']", ".companyLocation"],
      detail: [
        "#jobsearch-ViewjobPaneWrapper",
        ".jobsearch-RightPane",
        ".jobsearch-ViewJobLayout-jobDisplay",
        "#viewJobSSRRoot",
        ".jobsearch-JobComponent",
      ],
      description: ["#jobDescriptionText", "[data-testid='jobDescription']"],
      role: [
        "[data-testid='jobsearch-JobInfoHeader-title']",
        ".jobsearch-JobInfoHeader-title",
        "h1",
        "h2",
      ],
      company: [
        "[data-testid='inlineHeader-companyName']",
        "[data-company-name]",
        "[data-testid='jobsearch-CompanyInfoContainer'] a",
      ],
      location: [
        "[data-testid='inlineHeader-companyLocation']",
        "[data-testid='job-location']",
        "[data-testid='jobsearch-JobInfoHeader-companyLocation']",
      ],
      easyApply: [
        "#indeedApplyButton",
        ".ia-IndeedApplyButton",
        "[data-testid='indeedApply-button']",
        ".indeed-apply-button",
      ],
      externalApply: [
        "#applyButtonLinkContainer",
        "[data-testid='apply-button-container']",
        "button[aria-label*='company site']",
        "a[aria-label*='company site']",
      ],
      applyLinks: ["#applyButtonLinkContainer a", "[data-testid='apply-button-container'] a"],
    },
  };

  //: Minimum description length before a detail pane counts as loaded.
  const READY_CHARS = 200;

  function hostIs(host, part) {
    return host === part || host.endsWith(`.${part}`);
  }

  function parse(url) {
    try {
      return new URL(url);
    } catch {
      return null;
    }
  }

  function siteOf(url) {
    const parsed = parse(url);
    if (!parsed) return "";
    const host = parsed.hostname.toLowerCase();
    if (hostIs(host, "linkedin.com")) return "linkedin";
    if (hostIs(host, "indeed.com")) return "indeed";
    return "";
  }

  // {site, id, key} for the job a board URL shows (its own page or the search page's
  // detail pane), mirroring `identity.canonical_key`; null for anything else.
  function jobFromUrl(url) {
    const parsed = parse(url);
    const site = siteOf(url);
    if (!parsed || !site) return null;
    let id = "";
    if (site === "linkedin") {
      const view = parsed.pathname.match(/\/jobs\/view\/(?:[^/]*?-)?(\d+)/i);
      id = view ? view[1] : parsed.searchParams.get("currentJobId") || "";
      if (!/^\d+$/.test(id)) return null;
    } else {
      id = (parsed.searchParams.get("jk") || parsed.searchParams.get("vjk") || "").toLowerCase();
      if (!/^[0-9a-z]+$/.test(id)) return null;
    }
    return { site, id, key: `${site}:jobs:${id}` };
  }

  // The URL a board job is stored under (`routes/extension._board_url`).
  function jobUrl(site, id, host = "www.indeed.com") {
    return site === "linkedin"
      ? `https://www.linkedin.com/jobs/view/${id}/`
      : `https://${host}/viewjob?jk=${id}`;
  }

  function squash(value) {
    return (value || "").replace(/ /g, " ").replace(/\s+/g, " ").trim();
  }

  // Visible text of a title-ish element. LinkedIn repeats a title for screen readers
  // ("Analyst Analyst", "... with verification"), so a doubled phrase is halved.
  function titleText(element) {
    if (!element) return "";
    let text = squash(element.getAttribute?.("title") || element.textContent);
    text = text.replace(/\s+with verification$/i, "").trim();
    const words = text.split(" ");
    const half = words.length / 2;
    if (Number.isInteger(half) && half > 0 && words.slice(0, half).join(" ") === words.slice(half).join(" ")) {
      text = words.slice(0, half).join(" ");
    }
    return text;
  }

  function first(scope, selectors, read = (element) => squash(element.textContent)) {
    for (const selector of selectors) {
      for (const element of scope.querySelectorAll(selector)) {
        const value = read(element);
        if (value) return value;
      }
    }
    return "";
  }

  function linkedinCardId(element) {
    const direct = element.getAttribute("data-occludable-job-id") || element.getAttribute("data-job-id");
    if (direct && /^\d+$/.test(direct)) return direct;
    const urn = (element.getAttribute("data-entity-urn") || "").match(/jobPosting:(\d+)/);
    if (urn) return urn[1];
    const link = element.querySelector("a[href*='/jobs/view/']");
    const view = link?.getAttribute("href")?.match(/\/jobs\/view\/(?:[^/?]*?-)?(\d+)/);
    return view ? view[1] : "";
  }

  // The job cards listed on a search page: [{url, job_id, company, role, location, site}].
  function readCards(doc, pageUrl) {
    const site = siteOf(pageUrl);
    if (!site) return [];
    const rules = SELECTORS[site];
    const host = parse(pageUrl).hostname.toLowerCase();
    const seen = new Set();
    const cards = [];
    for (const selector of rules.cards) {
      for (const element of doc.querySelectorAll(selector)) {
        const id = site === "linkedin"
          ? linkedinCardId(element)
          : (element.getAttribute("data-jk") || "").toLowerCase();
        if (!id || seen.has(id)) continue;
        const card = site === "linkedin"
          ? element
          : rules.cardRoot.map((root) => element.closest(root)).find(Boolean) || element;
        const role = first(card, rules.cardTitle, titleText);
        if (!role) continue; // an occluded (scrolled-away) card
        seen.add(id);
        cards.push({
          url: jobUrl(site, id, host),
          job_id: id,
          company: first(card, rules.cardCompany),
          role,
          location: first(card, rules.cardLocation),
          site,
        });
      }
    }
    return cards;
  }

  // The element holding the open job's details, or null. A full job page falls back to
  // <main>; a search page never does, since its <main> also holds every other card.
  function detailContainer(doc, site) {
    const rules = SELECTORS[site];
    if (!rules) return null;
    for (const selector of rules.detail) {
      const found = doc.querySelector(selector);
      if (found) return found;
    }
    const path = parse(doc.location?.href || "")?.pathname || "";
    const jobPage = site === "linkedin" ? /\/jobs\/view\//.test(path) : /\/viewjob/.test(path);
    return jobPage ? doc.querySelector("main,[role='main']") || doc.body : null;
  }

  function applyKind(doc, site) {
    const container = detailContainer(doc, site);
    if (!container) return "unknown";
    const rules = SELECTORS[site];
    if (site === "indeed") {
      if (rules.easyApply.some((selector) => container.querySelector(selector))) return "easy_apply";
      if (rules.externalApply.some((selector) => container.querySelector(selector))) return "external";
      return "unknown";
    }
    const labels = rules.applyButtons
      .flatMap((selector) => [...container.querySelectorAll(selector)])
      .map((element) => squash(`${element.getAttribute("aria-label") || ""} ${element.textContent}`));
    if (labels.some((label) => /easy apply/i.test(label))) return "easy_apply";
    if (labels.some((label) => /\bapply\b/i.test(label))) return "external";
    return "unknown";
  }

  // The open job's own fields, read only from its detail container.
  function readDetail(doc, site) {
    const container = detailContainer(doc, site);
    if (!container) return null;
    const rules = SELECTORS[site];
    let role = first(container, rules.role, titleText);
    if (site === "indeed") role = role.replace(/\s*-\s*job post$/i, "");
    return {
      role,
      company: first(container, rules.company),
      // "New York, NY · 2 days ago · 90 applicants" -> "New York, NY"
      location: first(container, rules.location).split(" · ")[0].trim(),
      description: first(container, rules.description, (element) => {
        const text = element.innerText || element.textContent || "";
        return text.replace(/ /g, " ").trim();
      }),
      apply_kind: applyKind(doc, site),
    };
  }

  function detailReady(doc, site) {
    return (readDetail(doc, site)?.description.length || 0) >= READY_CHARS;
  }

  function applyLinkSelectors(site) {
    return SELECTORS[site]?.applyLinks || [];
  }

  root.RTSites = {
    SELECTORS,
    READY_CHARS,
    siteOf,
    jobFromUrl,
    jobUrl,
    readCards,
    detailContainer,
    readDetail,
    detailReady,
    applyKind,
    applyLinkSelectors,
  };
})(globalThis);
