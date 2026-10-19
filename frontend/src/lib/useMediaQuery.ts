import { useEffect, useState } from "react";

/** Whether a CSS media query matches, kept current as the window resizes. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const change = () => setMatches(list.matches);
    change();
    list.addEventListener("change", change);
    return () => list.removeEventListener("change", change);
  }, [query]);
  return matches;
}

/** The `lg` breakpoint, where pages put their panes side by side. */
export const WIDE = "(min-width: 1024px)";
