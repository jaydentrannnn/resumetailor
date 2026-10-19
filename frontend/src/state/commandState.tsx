import { type ReactNode, createContext, useContext, useEffect, useMemo, useRef } from "react";
import type { Command } from "../lib/commands";

type Source = { current: () => Command[] };
type Registry = { register: (source: Source) => () => void; list: () => Command[] };

const CommandContext = createContext<Registry | null>(null);

/**
 * Holds the commands mounted components offer to Ctrl+K. Each registers a builder that
 * is only called when the list opens, so registering never re-renders anything and the
 * list always reflects the page's state at that moment.
 */
export function CommandProvider({ children }: { children: ReactNode }) {
  const sources = useRef(new Set<Source>());
  const registry = useMemo<Registry>(
    () => ({
      register(source) {
        sources.current.add(source);
        return () => void sources.current.delete(source);
      },
      list: () => [...sources.current].flatMap((source) => source.current()),
    }),
    [],
  );
  return <CommandContext.Provider value={registry}>{children}</CommandContext.Provider>;
}

/** Offer commands while this component is mounted (a no-op outside `CommandProvider`). */
export function useCommands(build: () => Command[]): void {
  const registry = useContext(CommandContext);
  const source = useRef(build);
  source.current = build;
  useEffect(() => registry?.register(source), [registry]);
}

/** Every command offered right now, in the order they were registered. */
export function useCommandList(): () => Command[] {
  const registry = useContext(CommandContext);
  return registry?.list ?? (() => []);
}
