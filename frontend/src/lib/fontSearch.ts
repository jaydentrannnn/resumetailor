/** The font box's list: common fonts first, then every installed one, filtered by what
 * was typed (names starting with it before names containing it). */

export type FontGroup = { label: string; fonts: string[] };

function matches(fonts: string[], query: string): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return fonts;
  const starts = fonts.filter((f) => f.toLowerCase().startsWith(q));
  const contains = fonts.filter(
    (f) => !f.toLowerCase().startsWith(q) && f.toLowerCase().includes(q),
  );
  return [...starts, ...contains];
}

export function fontGroups(families: string[], common: string[], query: string): FontGroup[] {
  const usual = new Set(common);
  const groups = [
    { label: "Common", fonts: matches(common, query) },
    {
      label: "All installed",
      fonts: matches(
        families.filter((f) => !usual.has(f)),
        query,
      ),
    },
  ];
  return groups.filter((g) => g.fonts.length);
}

/** Whether `font` is installed here (case-insensitive, as Word matches font names). */
export function isInstalled(font: string, families: string[]): boolean {
  const name = font.trim().toLowerCase();
  return families.some((f) => f.toLowerCase() === name);
}
