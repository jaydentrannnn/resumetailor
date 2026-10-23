import type { CompanyFactKind, CompanyResearch, CompanySource, CompanySourceKind } from "../api";

export const FACT_KIND_LABELS: Record<CompanyFactKind, string> = {
  about: "About",
  product: "Product",
  mission: "Mission",
  values: "Values",
  size: "Size",
  news: "News",
};

const SOURCE_KIND_LABELS: Record<CompanySourceKind, string> = {
  posting: "Job posting",
  board: "Careers page",
  site: "Company site",
  news: "News",
  page: "Page you added",
  note: "Your note",
};

export function hostOf(url: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** A short name for a source: its site for a page, otherwise what kind it is. */
export function sourceLabel(source: CompanySource | undefined): string {
  if (!source) return "Unknown source";
  const host = hostOf(source.url);
  if (source.kind === "posting" || source.kind === "note" || source.kind === "board" || !host) {
    return SOURCE_KIND_LABELS[source.kind];
  }
  return host;
}

const LINK = /^(https?:\/\/)?[\w-]+(\.[\w-]+)+(\/\S*)?$/i;

/** What the "Add a page or note" box holds: a single link is a page, anything else a note. */
export function splitAddition(input: string): { urls: string[]; notes: string[] } {
  const text = input.trim();
  if (!text) return { urls: [], notes: [] };
  return LINK.test(text) ? { urls: [text], notes: [] } : { urls: [], notes: [text] };
}

/** "6 sources · read 20 Oct 2026", or "" before any research. */
export function researchMeta(research: CompanyResearch | null): string {
  if (!research) return "";
  const count = research.sources.length;
  const day = research.researched_at.slice(0, 10);
  const when = day ? ` · read ${formatDay(day)}` : "";
  return `${count} ${count === 1 ? "source" : "sources"}${when}`;
}

export function formatDay(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** Plain lines about what was left out, for under the facts. */
export function researchNotes(research: CompanyResearch): string[] {
  const notes = [...research.warnings];
  if (research.dropped) {
    notes.push(
      `${research.dropped} ${research.dropped === 1 ? "fact was" : "facts were"} left out: ` +
        "the quoted words were not in the source.",
    );
  }
  return notes;
}
