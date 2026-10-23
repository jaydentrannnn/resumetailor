/** LinkedIn's people search; the link only opens in the browser, the app never fetches it. */
const PEOPLE_SEARCH = "https://www.linkedin.com/search/results/people/";

/** Words in a posting title that say when or how, not what the job is. */
const NOISE =
  /\b(?:intern(?:ship)?s?|co-?op|summer|fall|spring|winter|20\d\d|junior|jr|new grad(?:uate)?|entry[- ]level|part[- ]time|full[- ]time|remote|hybrid|ii|iii|iv)\b/gi;

/** The job in a posting title: "Data Analyst Intern (Summer 2026) - NYC" → "Data Analyst". */
export function roleKeyword(role: string): string {
  const head = role.replace(/\(.*?\)|\[.*?\]/g, " ").split(/\s[-–—|,]\s|,/)[0];
  return head.replace(NOISE, " ").replace(/\s+/g, " ").trim();
}

export type ReferralSearch = { label: string; url: string };

/** People to ask for a referral: the company's recruiters, and people in this role there. */
export function referralSearches(company: string, role: string): ReferralSearch[] {
  const name = company.trim();
  if (!name) return [];
  const search = (keywords: string) => `${PEOPLE_SEARCH}?keywords=${encodeURIComponent(keywords)}`;
  const searches = [{ label: `Recruiters at ${name}`, url: search(`${name} recruiter`) }];
  const keyword = roleKeyword(role);
  if (keyword) searches.push({ label: `${keyword} at ${name}`, url: search(`${name} ${keyword}`) });
  return searches;
}
