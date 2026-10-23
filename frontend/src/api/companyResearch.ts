import { request } from "./core";

export type CompanySourceKind = "posting" | "board" | "site" | "news" | "page" | "note";
export type CompanyFactKind = "about" | "product" | "mission" | "values" | "size" | "news";

/** One text the facts were read from (`company_store.Source`). */
export type CompanySource = {
  id: string;
  kind: CompanySourceKind;
  url: string | null;
  title: string;
  fetched_at: string;
  sha: string;
  text: string;
  flags: string[];
};

/** A fact with the source words that state it. */
export type CompanyFact = {
  id: string;
  text: string;
  kind: CompanyFactKind;
  source_id: string;
  excerpt: string;
  as_of: string;
};

export type CompanyResearch = {
  company: string;
  researched_at: string;
  sources: CompanySource[];
  facts: CompanyFact[];
  removed: string[];
  dropped: number;
  searched_with: string;
  warnings: string[];
  model: string;
};

export type CompanyResearchView = {
  company: string;
  research: CompanyResearch | null;
  stale: boolean;
  /** "brave" or "tavily" when a search key is saved, else "". */
  search: string;
};

export type CompanyResearchRequest = {
  site_url?: string;
  urls?: string[];
  notes?: string[];
  refresh?: boolean;
};

const path = (sourceJobId: string) =>
  `/api/applications/${encodeURIComponent(sourceJobId)}/company-research`;

export function getCompanyResearch(sourceJobId: string): Promise<CompanyResearchView> {
  return request(path(sourceJobId));
}

/** Research the company, or add pages and notes to what was read before. */
export function researchCompany(
  sourceJobId: string,
  body: CompanyResearchRequest,
): Promise<CompanyResearchView> {
  return request(path(sourceJobId), { method: "POST", body: JSON.stringify(body) });
}

export function removeCompanyFact(
  sourceJobId: string,
  factId: string,
): Promise<CompanyResearchView> {
  return request(`${path(sourceJobId)}/facts/${encodeURIComponent(factId)}`, {
    method: "DELETE",
  });
}
