import type { BoardConfig, SourceConfig } from "../api";
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

function sameBoard(a: BoardConfig, b: BoardConfig): boolean {
  return a.ats === b.ats && a.slug.toLowerCase() === b.slug.toLowerCase();
}

/** Add ``board`` unless the watchlist already has it. */
export function addBoard(boards: BoardConfig[], board: BoardConfig): BoardConfig[] {
  return boards.some((b) => sameBoard(b, board)) ? boards : [...boards, board];
}

export function removeBoard(boards: BoardConfig[], board: BoardConfig): BoardConfig[] {
  return boards.filter((b) => !sameBoard(b, board));
}

export function hasBoard(boards: BoardConfig[], board: BoardConfig): boolean {
  return boards.some((b) => sameBoard(b, board));
}

export const ATS_LABELS: Record<BoardConfig["ats"], string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  workday: "Workday",
};
