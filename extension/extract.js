(() => {
  const page = new URL(location.href);
  const host = page.hostname.toLowerCase();
  const visible = (element) => {
    if (!element || element.closest("script,style,nav,header,footer,dialog,[hidden],[aria-hidden='true']")) return false;
    const style = getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  };
  const text = (element) => visible(element) ? (element.innerText || element.textContent || "").replace(/\u00a0/g, " ").trim() : "";
  const firstText = (...selectors) => {
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        const value = text(element);
        if (value) return value;
      }
    }
    return "";
  };
  const meta = (name) => document.querySelector(`meta[property='${name}'],meta[name='${name}']`)?.content?.trim() || "";
  const hostname = (part) => host === part || host.endsWith(`.${part}`);
  let ats = "unknown";
  let description = "";
  let role = "";
  let company = "";
  let jobLocation = "";
  if (hostname("linkedin.com")) {
    ats = "linkedin";
    description = firstText(".jobs-description", ".jobs-description-content__text", "#job-details");
    role = firstText(".job-details-jobs-unified-top-card__job-title", ".jobs-unified-top-card__job-title", "h1");
    company = firstText(".job-details-jobs-unified-top-card__company-name", ".jobs-unified-top-card__company-name");
    jobLocation = firstText(".job-details-jobs-unified-top-card__tertiary-description-container", ".jobs-unified-top-card__bullet");
  } else if (hostname("joinhandshake.com")) {
    ats = "handshake";
    description = firstText("[data-hook='job-description']", "[data-testid='job-description']", ".job-description");
    role = firstText("h1");
    company = firstText("[data-hook='job-employer-name']", "[data-testid='employer-name']");
    jobLocation = firstText("[data-hook='job-location']", "[data-testid='job-location']");
  } else if (hostname("indeed.com")) {
    ats = "indeed";
    description = firstText("#jobDescriptionText", "[data-testid='jobDescription']");
    role = firstText("[data-testid='jobsearch-JobInfoHeader-title']", "h1");
    company = firstText("[data-testid='inlineHeader-companyName']", "[data-company-name]");
    jobLocation = firstText("[data-testid='job-location']", "[data-testid='jobsearch-JobInfoHeader-companyLocation']");
  } else if (host.includes("greenhouse.io")) {
    ats = "greenhouse";
    description = firstText("#content", ".job-post-content", "[data-testid='job-description']");
    role = firstText("h1");
    company = firstText(".company-name", ".employer-name");
    jobLocation = firstText(".location", "[data-testid='location']");
  } else if (host.includes("lever.co")) {
    ats = "lever";
    description = firstText(".section-wrapper", ".posting-description", ".posting-page .content");
    role = firstText(".posting-headline h2", "h1");
    company = firstText(".main-header-logo + span", ".company-name");
    jobLocation = firstText(".posting-categories .location", ".location");
  } else if (host.includes("ashbyhq.com")) {
    ats = "ashby";
    description = firstText("[data-testid='job-description']", ".ashby-job-posting-description", "main article");
    role = firstText("h1");
    company = firstText("[data-testid='company-name']");
    jobLocation = firstText("[data-testid='job-location']");
  } else if (host.includes("myworkdayjobs.com")) {
    ats = "workday";
    description = firstText("[data-automation-id='jobPostingDescription']");
    role = firstText("[data-automation-id='jobPostingHeader']", "h1");
    company = firstText("[data-automation-id='company']");
    jobLocation = firstText("[data-automation-id='locations']");
  } else if (host.includes("icims.com")) {
    ats = "icims";
    const frame = document.querySelector("iframe#icims_content_iframe,iframe[name='icims_content_iframe']");
    try {
      description = text(frame?.contentDocument?.body);
      role = frame?.contentDocument?.querySelector("h1")?.textContent?.trim() || "";
    } catch {
      // A cross-origin frame cannot be read with activeTab. Selection capture remains available.
    }
  }
  if (!description) {
    const candidates = [...document.querySelectorAll("main,article,section,[role='main']")]
      .filter(visible)
      .map((element) => {
        const own = text(element);
        const child = [...element.querySelectorAll("main,article,section,[role='main']")]
          .filter(visible).map(text).sort((a, b) => b.length - a.length)[0] || "";
        return child.length > own.length * 0.7 ? child : own;
      })
      .filter((value) => value.length > 100);
    description = candidates.sort((a, b) => b.length - a.length)[0] || "";
  }
  if (/^(sign in|log in|create an account|join now)/i.test(description) && description.length < 400) {
    description = "";
  }
  role ||= firstText("h1") || meta("og:title");
  company ||= meta("og:site_name");
  jobLocation ||= firstText("[data-testid='location']", ".location");
  const applyLink = [...document.querySelectorAll("a[href]")]
    .filter(visible)
    .find((anchor) => /\bapply\b/i.test(text(anchor)) && !/privacy|policy/i.test(text(anchor)));
  let applyUrl = "";
  if (applyLink) {
    try {
      const candidate = new URL(applyLink.getAttribute("href"), location.href);
      const nested = hostname("linkedin.com") && candidate.pathname.includes("/redir/redirect")
        ? candidate.searchParams.get("url") : null;
      const resolved = nested ? new URL(nested) : candidate;
      if (["http:", "https:"].includes(resolved.protocol)) applyUrl = resolved.href;
    } catch {
      // Invalid links are ignored.
    }
  }
  return {
    url: location.href,
    final_url: document.URL,
    apply_url: applyUrl,
    company: company.slice(0, 200),
    role: role.slice(0, 300),
    location: jobLocation.slice(0, 300),
    jd_text: description,
    ats_guess: ats,
  };
})()
