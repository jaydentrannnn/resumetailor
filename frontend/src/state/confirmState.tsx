import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Modal } from "../components/Modal";

type ConfirmTone = "default" | "danger";

type ConfirmOpts = {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: ConfirmTone;
};

type ChoiceOption = {
  id: string;
  label: string;
  tone?: ConfirmTone;
};

type ChoiceOpts = {
  title: string;
  message: string;
  options: ChoiceOption[];
  cancelLabel?: string;
};

type ConfirmStateValue = {
  /** Resolves true if the user confirmed, false if they cancelled / closed. */
  confirm: (opts: ConfirmOpts) => Promise<boolean>;
  /** Resolves the chosen option id, or null if cancelled / closed. */
  choice: (opts: ChoiceOpts) => Promise<string | null>;
};

const ConfirmStateContext = createContext<ConfirmStateValue | null>(null);

type ActiveDialog =
  | {
      kind: "confirm";
      opts: ConfirmOpts;
      resolve: (value: boolean) => void;
    }
  | {
      kind: "choice";
      opts: ChoiceOpts;
      resolve: (value: string | null) => void;
    };

/**
 * Promise-based confirm / multi-choice dialogs replacing `window.confirm`.
 *
 * Mount above the keyed Run/Editor/Template providers so a profile switch cannot
 * unmount a dialog the user is mid-decision on (ProfileSwitcher itself needs this).
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<ActiveDialog | null>(null);
  // Queue so a second confirm while one is open still resolves in order rather than
  // silently replacing the first dialog's promise.
  const queueRef = useRef<ActiveDialog[]>([]);

  const showNext = useCallback(() => {
    const next = queueRef.current.shift() ?? null;
    setActive(next);
  }, []);

  const confirm = useCallback((opts: ConfirmOpts) => {
    return new Promise<boolean>((resolve) => {
      const entry: ActiveDialog = { kind: "confirm", opts, resolve };
      setActive((current) => {
        if (current) {
          queueRef.current.push(entry);
          return current;
        }
        return entry;
      });
    });
  }, []);

  const choice = useCallback((opts: ChoiceOpts) => {
    return new Promise<string | null>((resolve) => {
      const entry: ActiveDialog = { kind: "choice", opts, resolve };
      setActive((current) => {
        if (current) {
          queueRef.current.push(entry);
          return current;
        }
        return entry;
      });
    });
  }, []);

  const closeWith = useCallback(
    (result: boolean | string | null) => {
      if (!active) return;
      if (active.kind === "confirm") active.resolve(Boolean(result));
      else active.resolve(typeof result === "string" ? result : null);
      showNext();
    },
    [active, showNext],
  );

  const value = useMemo(() => ({ confirm, choice }), [confirm, choice]);

  return (
    <ConfirmStateContext.Provider value={value}>
      {children}
      {active?.kind === "confirm" && (
        <Modal title={active.opts.title} onClose={() => closeWith(false)}>
          <p className="mt-3 whitespace-pre-line text-sm text-ink">{active.opts.message}</p>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => closeWith(false)}
              autoFocus={active.opts.tone === "danger"}
              className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink-muted hover:border-accent hover:text-accent"
            >
              {active.opts.cancelLabel ?? "Cancel"}
            </button>
            <button
              type="button"
              onClick={() => closeWith(true)}
              autoFocus={active.opts.tone !== "danger"}
              className={
                active.opts.tone === "danger"
                  ? "rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-on-accent hover:bg-danger/85"
                  : "rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent hover:bg-accent/90"
              }
            >
              {active.opts.confirmLabel ?? "Confirm"}
            </button>
          </div>
        </Modal>
      )}
      {active?.kind === "choice" && (
        <Modal title={active.opts.title} onClose={() => closeWith(null)}>
          <p className="mt-3 whitespace-pre-line text-sm text-ink">{active.opts.message}</p>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => closeWith(null)}
              className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink-muted hover:border-accent hover:text-accent"
            >
              {active.opts.cancelLabel ?? "Cancel"}
            </button>
            {active.opts.options.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => closeWith(opt.id)}
                className={
                  opt.tone === "danger"
                    ? "rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-on-accent hover:bg-danger/85"
                    : "rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent hover:bg-accent/90"
                }
              >
                {opt.label}
              </button>
            ))}
          </div>
        </Modal>
      )}
    </ConfirmStateContext.Provider>
  );
}

/**
 * Access confirm / choice dialogs. Must be used under `ConfirmProvider`.
 */
export function useConfirm(): ConfirmStateValue {
  const ctx = useContext(ConfirmStateContext);
  if (!ctx) {
    throw new Error("useConfirm must be used within ConfirmProvider");
  }
  return ctx;
}
