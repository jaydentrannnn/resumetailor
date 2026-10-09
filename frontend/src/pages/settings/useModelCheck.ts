import { useCallback, useEffect, useRef, useState } from "react";
import { testModel, type CheckResult, type JobSettings } from "../../api";
import { emitAppEvent } from "../../lib/appEvents";
import { describe } from "../../lib/errors";

export type ModelTarget = "tailor" | "autofill";
export type ModelCheck = CheckResult | "testing" | null;

const DEBOUNCE_MS = 800;
/** Results by target + provider + model, so switching tabs or pages never retests. */
const results = new Map<string, CheckResult>();
const listeners = new Set<() => void>();
/** Tests in flight, so two components showing the same model share one call. */
const pending = new Map<string, Promise<CheckResult>>();

function test(key: string, target: ModelTarget, settings: JobSettings): Promise<CheckResult> {
  let call = pending.get(key);
  if (!call) {
    call = testModel(settings, target)
      .catch((err): CheckResult => ({ ok: false, detail: describe(err).detail }))
      .then((result) => {
        results.set(key, result);
        listeners.forEach((listener) => listener());
        if (result.ok) emitAppEvent("rt:setup-changed");
        return result;
      })
      .finally(() => pending.delete(key));
    pending.set(key, call);
  }
  return call;
}

function keyFor(target: ModelTarget, settings: JobSettings): string {
  return target === "tailor"
    ? `tailor|${settings.model}|${settings.model_name ?? ""}`
    : `autofill|${settings.apply.model_provider}|${settings.apply.model_name}`;
}

/** Forget every result and retest what is on screen (a key was saved or removed). */
export function clearModelChecks(): void {
  results.clear();
  listeners.forEach((listener) => listener());
}

/**
 * Tests `target`'s model automatically: once ~1 s after the provider or model settles,
 * and again after any key change. Skipped while `ready` is false (a key is missing, or
 * settings have not loaded), so the test never spends a call that is bound to fail.
 */
export function useModelCheck(target: ModelTarget, settings: JobSettings, ready: boolean) {
  const key = keyFor(target, settings);
  const [check, setCheck] = useState<ModelCheck>(() => results.get(key) ?? null);
  const [generation, setGeneration] = useState(0);
  const latest = useRef(key);
  latest.current = key;

  useEffect(() => {
    const listener = () => setGeneration((n) => n + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const run = useCallback(async () => {
    // Another component may have finished the same test since this one was scheduled.
    const cached = results.get(key);
    if (!cached) setCheck("testing");
    const result = cached ?? (await test(key, target, settings));
    // A result for a provider/model no longer on screen only fills the cache.
    if (latest.current === key) setCheck(result);
    // `settings` changes on every edit; the key captures what the test depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, target]);

  useEffect(() => {
    const cached = results.get(key);
    if (cached) {
      setCheck(cached);
      return;
    }
    setCheck(null);
    if (!ready) return;
    const timer = window.setTimeout(() => void run(), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [key, ready, run, generation]);

  const retest = useCallback(() => {
    results.delete(key);
    void run();
  }, [key, run]);

  return { check, retest };
}
