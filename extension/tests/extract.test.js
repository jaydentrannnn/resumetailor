import { test } from "node:test";
import assert from "node:assert/strict";
import { loadPage, runExtract } from "./dom.js";

test("LinkedIn search page captures the open job, not the list", () => {
  const url = "https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=analyst";
  const data = runExtract(loadPage("linkedin-search.html", url));
  assert.equal(data.url, url);
  assert.equal(data.ats_guess, "linkedin");
  assert.deepEqual([data.role, data.company, data.location], ["Summer Analyst", "Acme Capital", "New York, NY"]);
  assert.equal(data.apply_kind, "easy_apply");
  assert.equal(data.apply_url, "");
  assert.match(data.jd_text, /^About the job/);
  assert.doesNotMatch(data.jd_text, /Globex|Privacy/);
});

test("Indeed search pane captures the selected job", () => {
  const url = "https://www.indeed.com/jobs?q=analyst&vjk=a1b2c3d4e5f60718";
  const data = runExtract(loadPage("indeed-search.html", url));
  assert.equal(data.ats_guess, "indeed");
  assert.deepEqual([data.role, data.company], ["Financial Analyst", "Initech"]);
  assert.equal(data.apply_kind, "external");
  assert.match(data.jd_text, /monthly forecasts/);
  assert.doesNotMatch(data.jd_text, /Operations Intern/);
});

test("a board page with nothing open captures no description", () => {
  const data = runExtract(loadPage(
    "<main><article>" + "Browse thousands of jobs near you. ".repeat(10) + "</article></main>",
    "https://www.linkedin.com/jobs/search/?keywords=a",
  ));
  assert.equal(data.jd_text, "");
});
