import { createContext, useContext } from "react";
import type { SourceFilters } from "../../api";

/** What a source panel needs to know about the filters for every source. */
export type EverySource = {
  filters: SourceFilters;
  /** The eligibility line, read-only in a source ("Skips no visa sponsorship, …"). */
  eligibility: string;
  /** Close the source panel and open "Filters for every source" for editing. */
  openGlobal: () => void;
};

/** Provided by the Job sources page; null where a source editor is used without it. */
export const EverySourceContext = createContext<EverySource | null>(null);

export const useEverySource = () => useContext(EverySourceContext);
