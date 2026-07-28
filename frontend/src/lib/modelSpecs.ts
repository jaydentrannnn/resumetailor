import { useSyncExternalStore } from "react";

/** localStorage key for the shared rewrite/expand model-spec list. */
const STORAGE_KEY = "resumeTailor.modelSpecs";

/** Seeded on first load from the project's default Anthropic and Ollama specs. */
const DEFAULT_SPECS = ["claude-sonnet-5", "ollama:gemma4:cloud"];

type Listener = () => void;

const listeners = new Set<Listener>();

/**
 * Read the saved model-spec list from localStorage, seeding defaults on first use.
 */
function readSpecs(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw == null) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_SPECS));
      return [...DEFAULT_SPECS];
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [...DEFAULT_SPECS];
    return parsed
      .filter((s): s is string => typeof s === "string")
      .map((s) => s.trim())
      .filter(Boolean);
  } catch {
    return [...DEFAULT_SPECS];
  }
}

/**
 * Persist `specs` and notify every subscribed React root (and other tabs via storage).
 */
function writeSpecs(specs: string[]): void {
  const unique = [...new Set(specs.map((s) => s.trim()).filter(Boolean))];
  localStorage.setItem(STORAGE_KEY, JSON.stringify(unique));
  for (const listener of listeners) listener();
}

/**
 * Subscribe to local changes and to `storage` events from other tabs.
 */
function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === STORAGE_KEY || e.key === null) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/**
 * Snapshot for `useSyncExternalStore`. Returning a new array each time would loop;
 * we stringify as the cache key and only allocate when the payload changes.
 */
let cachedJson = "";
let cachedSpecs: string[] = [];

function getSnapshot(): string[] {
  const specs = readSpecs();
  const json = JSON.stringify(specs);
  if (json !== cachedJson) {
    cachedJson = json;
    cachedSpecs = specs;
  }
  return cachedSpecs;
}

function getServerSnapshot(): string[] {
  /** SSR / first-paint fallback before localStorage is available. */
  return DEFAULT_SPECS;
}

/**
 * Shared rewrite/expand model-spec list. Both Settings fields read this store so a
 * spec added on one side appears on the other immediately.
 */
export function useModelSpecs(): {
  specs: string[];
  addSpec: (spec: string) => void;
  removeSpec: (spec: string) => void;
} {
  const specs = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  function addSpec(spec: string) {
    /** Append a trimmed spec if it is non-empty and not already present. */
    const trimmed = spec.trim();
    if (!trimmed) return;
    const current = readSpecs();
    if (current.includes(trimmed)) return;
    writeSpecs([...current, trimmed]);
  }

  function removeSpec(spec: string) {
    /** Drop `spec` from the shared list. */
    writeSpecs(readSpecs().filter((s) => s !== spec));
  }

  return { specs, addSpec, removeSpec };
}
