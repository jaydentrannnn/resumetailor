import { test } from "node:test";
import assert from "node:assert/strict";
import { loadPage, runExtract } from "./dom.js";

test("unwraps LinkedIn redirects and ignores links back into the board", () => {
  const { RTApplyLink: links } = loadPage("<p></p>", "https://www.linkedin.com/jobs/view/1/");
  const base = "https://www.linkedin.com/jobs/view/1/";
  assert.equal(
    links.unwrap("/redir/redirect?url=https%3A%2F%2Fboards.greenhouse.io%2Facme%2Fjobs%2F5&urlhash=x", base),
    "https://boards.greenhouse.io/acme/jobs/5",
  );
  assert.equal(links.unwrap("https://www.linkedin.com/safety/go?url=https%3A%2F%2Facme.com%2Fjobs%2F9", base), "https://acme.com/jobs/9");
  assert.equal(links.unwrap("/jobs/view/2/", base), "");
  assert.equal(links.unwrap("https://www.indeed.com/applystart?jk=1", base), "");
  assert.equal(links.unwrap("javascript:void(0)", base), "");
  assert.equal(links.unwrap("/redir/redirect?url=javascript%3Aalert(1)", base), "");
  assert.equal(links.unwrap("", base), "");
});

test("the apply link comes from the job's own container, not a sidebar", () => {
  const url = "https://www.linkedin.com/jobs/view/research-associate-at-hooli-4099/";
  const window = loadPage("linkedin-view-external.html", url);
  assert.equal(
    window.RTApplyLink.findApplyLink(window.document, { site: "linkedin", baseUrl: url }),
    "https://jobs.lever.co/hooli/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab/apply",
  );
  const data = runExtract(window);
  assert.equal(data.apply_url, "https://jobs.lever.co/hooli/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab/apply");
  assert.equal(data.apply_kind, "external");
});

test("a search page with no open job has no apply link", () => {
  const window = loadPage(
    "<main><a href='/redir/redirect?url=https%3A%2F%2Fa.test%2Fjob'>Apply</a></main>",
    "https://www.linkedin.com/jobs/search/?keywords=a",
  );
  assert.equal(window.RTApplyLink.findApplyLink(window.document, { site: "linkedin" }), "");
});

test("an Easy Apply pane has no external link", () => {
  const url = "https://www.linkedin.com/jobs/search/?currentJobId=4012345678";
  const window = loadPage("linkedin-search.html", url);
  assert.equal(window.RTApplyLink.findApplyLink(window.document, { site: "linkedin", baseUrl: url }), "");
});

test("on other sites, navigation and policy links are skipped", () => {
  const window = loadPage(
    `<header><a href="https://acme.test/apply-everywhere">Apply</a></header>
     <main><a href="/privacy">Apply privacy policy</a><a href="/jobs/5/apply">Apply for this job</a></main>`,
    "https://careers.acme.test/jobs/5",
  );
  assert.equal(window.RTApplyLink.findApplyLink(window.document, {}), "https://careers.acme.test/jobs/5/apply");
});
