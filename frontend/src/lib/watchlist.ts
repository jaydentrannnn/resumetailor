import type { SourceConfig, WatchlistCompany } from "../api";
import { uniqueSourceId } from "./sources";

/** Title words a business watchlist starts with; the student edits them freely. */
export const BUSINESS_INCLUDE = [
  "analyst",
  "intern",
  "associate",
  "finance",
  "consult",
  "strategy",
  "operations",
  "rotational",
  "development program",
];
export const DEFAULT_EXCLUDE = ["senior", "director", "principal", "phd", "vice president"];

/** The first watchlist's id (older profiles have exactly this one); later ones get `-2`, `-3`… */
export const WATCHLIST_ID = "company-watchlist";

/** A new, empty watchlist whose id no source in ``existing`` uses. */
export function newWatchlistSource(
  include: string[] = BUSINESS_INCLUDE,
  existing: Pick<SourceConfig, "id">[] = [],
): SourceConfig {
  return {
    id: uniqueSourceId(WATCHLIST_ID, existing),
    kind: "ats_board",
    url: "",
    categories: [],
    enabled: true,
    boards: [],
    include: [...include],
    exclude: [...DEFAULT_EXCLUDE],
    locations: [],
    max_age_days: 7,
  };
}

/** "analyst, intern,, Finance " → ["analyst", "intern", "Finance"] (order kept, no repeats). */
export function parseWords(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/[,\n]/)) {
    const word = raw.trim();
    const key = word.toLowerCase();
    if (word && !seen.has(key)) {
      seen.add(key);
      out.push(word);
    }
  }
  return out;
}

export function watchlistCompanies(source: SourceConfig): WatchlistCompany[] {
  const indexed = source.provider === "freehire" ? source.categories : [];
  return [
    ...(source.boards ?? []),
    ...indexed.map((slug) => ({ ats: "freehire" as const, slug, company: slug })),
  ];
}

/** Keep indexed employer IDs separate from ATS boards so older desktops can save the watchlist. */
export function withCompanies(source: SourceConfig, companies: WatchlistCompany[]): SourceConfig {
  const boards = companies.flatMap(({ ats, slug, company }) =>
    ats === "freehire" ? [] : [{ ats, slug, company }],
  );
  const indexed = companies.filter((b) => b.ats === "freehire").map((b) => b.slug);
  if (indexed.length || source.provider === "freehire")
    return { ...source, boards, provider: "freehire", categories: indexed };
  return { ...source, boards };
}

function sameBoard(a: WatchlistCompany, b: WatchlistCompany): boolean {
  return a.ats === b.ats && a.slug.toLowerCase() === b.slug.toLowerCase();
}

/** Add ``board`` unless the watchlist already has it. */
export function addBoard(boards: WatchlistCompany[], board: WatchlistCompany): WatchlistCompany[] {
  return boards.some((b) => sameBoard(b, board)) ? boards : [...boards, board];
}

export function removeBoard(
  boards: WatchlistCompany[],
  board: WatchlistCompany,
): WatchlistCompany[] {
  return boards.filter((b) => !sameBoard(b, board));
}

export function hasBoard(boards: WatchlistCompany[], board: WatchlistCompany): boolean {
  return boards.some((b) => sameBoard(b, board));
}

export const ATS_LABELS: Record<WatchlistCompany["ats"], string> = {
  freehire: "FreeHire employer index",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  workday: "Workday",
};
