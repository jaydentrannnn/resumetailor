import { test } from "node:test";
import assert from "node:assert/strict";
import { loadPage } from "./dom.js";

const LINKEDIN_SEARCH = "https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=analyst";
const INDEED_SEARCH = "https://www.indeed.com/jobs?q=analyst&l=Austin&vjk=a1b2c3d4e5f60718";
// Values built inside the jsdom window use its own Array/Object.
const plain = (value) => JSON.parse(JSON.stringify(value));

test("job keys mirror identity.canonical_key for board URLs", () => {
  const { RTSites: sites } = loadPage("<p></p>", "https://example.test/");
  const key = (url) => sites.jobFromUrl(url)?.key || null;
  assert.equal(key("https://www.linkedin.com/jobs/view/summer-analyst-at-acme-4012345678/"), "linkedin:jobs:4012345678");
  assert.equal(key(LINKEDIN_SEARCH), "linkedin:jobs:4012345678");
  assert.equal(key("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=77"), "linkedin:jobs:77");
  assert.equal(key("https://www.indeed.com/viewjob?jk=AB12cd"), "indeed:jobs:ab12cd");
  assert.equal(key(INDEED_SEARCH), "indeed:jobs:a1b2c3d4e5f60718");
  assert.equal(key("https://uk.indeed.com/jobs?q=x&vjk=ff00"), "indeed:jobs:ff00");
  assert.equal(key("https://www.linkedin.com/jobs/search/?keywords=analyst"), null);
  assert.equal(key("https://www.indeed.com/jobs?q=analyst"), null);
  assert.equal(key("https://boards.greenhouse.io/acme/jobs/1"), null);
  assert.equal(sites.jobUrl("indeed", "abc", "ca.indeed.com"), "https://ca.indeed.com/viewjob?jk=abc");
});

test("reads LinkedIn search cards, skipping ones scrolled out of view", () => {
  const window = loadPage("linkedin-search.html", LINKEDIN_SEARCH);
  const cards = plain(window.RTSites.readCards(window.document, window.location.href));
  assert.deepEqual(cards, [
    {
      url: "https://www.linkedin.com/jobs/view/4012345678/",
      job_id: "4012345678",
      company: "Acme Capital",
      role: "Summer Analyst",
      location: "New York, NY (On-site)",
      site: "linkedin",
    },
    {
      url: "https://www.linkedin.com/jobs/view/4012345679/",
      job_id: "4012345679",
      company: "Globex",
      role: "Data Analyst Intern",
      location: "Remote",
      site: "linkedin",
    },
  ]);
});

test("reads Indeed search cards", () => {
  const window = loadPage("indeed-search.html", INDEED_SEARCH);
  const cards = plain(window.RTSites.readCards(window.document, window.location.href));
  assert.deepEqual(cards.map((card) => [card.job_id, card.role, card.company, card.location, card.url]), [
    ["a1b2c3d4e5f60718", "Financial Analyst", "Initech", "Austin, TX 78701", "https://www.indeed.com/viewjob?jk=a1b2c3d4e5f60718"],
    ["ffee0011aabb2233", "Operations Intern", "Hooli", "Remote", "https://www.indeed.com/viewjob?jk=ffee0011aabb2233"],
  ]);
});

test("reads only the open job's pane on a search page", () => {
  const window = loadPage("linkedin-search.html", LINKEDIN_SEARCH);
  const detail = window.RTSites.readDetail(window.document, "linkedin");
  assert.equal(detail.role, "Summer Analyst");
  assert.equal(detail.company, "Acme Capital");
  assert.equal(detail.location, "New York, NY");
  assert.equal(detail.apply_kind, "easy_apply");
  assert.match(detail.description, /build financial models/);
  assert.doesNotMatch(detail.description, /Data Analyst Intern/);
  assert.ok(window.RTSites.detailReady(window.document, "linkedin"));

  const indeed = loadPage("indeed-search.html", INDEED_SEARCH);
  const pane = indeed.RTSites.readDetail(indeed.document, "indeed");
  assert.equal(pane.role, "Financial Analyst");
  assert.equal(pane.company, "Initech");
  assert.equal(pane.apply_kind, "external");
  assert.doesNotMatch(pane.description, /Operations Intern/);
});

test("Indeed's own apply form is easy apply", () => {
  const window = loadPage("indeed-viewjob.html", "https://www.indeed.com/viewjob?jk=0a0b0c0d");
  const detail = window.RTSites.readDetail(window.document, "indeed");
  assert.equal(detail.role, "Staff Accountant");
  assert.equal(detail.location, "Denver, CO");
  assert.equal(detail.apply_kind, "easy_apply");
});

test("a search page without an open job has no detail container", () => {
  const window = loadPage(
    "<main><ul><li data-occludable-job-id='1'><a class='job-card-list__title--link' href='/jobs/view/1/'>A</a></li></ul></main>",
    "https://www.linkedin.com/jobs/search/?keywords=a",
  );
  assert.equal(window.RTSites.detailContainer(window.document, "linkedin"), null);
  assert.equal(window.RTSites.applyKind(window.document, "linkedin"), "unknown");
  assert.equal(window.RTSites.detailReady(window.document, "linkedin"), false);
});
