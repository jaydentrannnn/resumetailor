import { type ReactNode, useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import {
  defaultTimeout,
  type Toast,
  type ToastApi,
  ToastContext,
  type ToastInput,
  toastReducer,
} from "../../lib/toast";

const KIND_CLASS: Record<Toast["kind"], string> = {
  success: "border-success/40 bg-success-soft text-success",
  error: "border-danger/40 bg-danger-soft text-danger",
  info: "border-info/40 bg-info-soft text-info",
};

/** Provides `useToast()` and renders the stack in the bottom-right corner. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, dispatch] = useReducer(toastReducer, []);
  const nextId = useRef(1);
  const dismiss = useCallback((id: number) => dispatch({ type: "dismiss", id }), []);
  const show = useCallback((input: ToastInput) => {
    const id = nextId.current++;
    const timeoutMs = input.timeoutMs === undefined ? defaultTimeout(input.kind) : input.timeoutMs;
    dispatch({ type: "push", toast: { ...input, id, timeoutMs } });
    return id;
  }, []);
  const api = useMemo<ToastApi>(
    () => ({
      show,
      dismiss,
      success: (title, detail, action) => show({ kind: "success", title, detail, action }),
      error: (title, detail, action) => show({ kind: "error", title, detail, action }),
      info: (title, detail, action) => show({ kind: "info", title, detail, action }),
    }),
    [show, dismiss],
  );
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] flex flex-col items-end gap-2 sm:left-auto sm:w-96">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    if (toast.timeoutMs == null) return;
    const timer = window.setTimeout(() => onDismiss(toast.id), toast.timeoutMs);
    return () => window.clearTimeout(timer);
  }, [toast.id, toast.timeoutMs, onDismiss]);
  return (
    <div
      role={toast.kind === "error" ? "alert" : "status"}
      className={`pointer-events-auto w-full rounded-lg border px-4 py-3 text-sm shadow-lg ${KIND_CLASS[toast.kind]}`}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{toast.title}</p>
          {toast.detail && (
            <p className="mt-1 whitespace-pre-line break-words text-ink">{toast.detail}</p>
          )}
          {toast.action && (
            <button
              type="button"
              className="mt-2 font-semibold underline underline-offset-2"
              onClick={() => {
                toast.action?.onClick();
                onDismiss(toast.id);
              }}
            >
              {toast.action.label}
            </button>
          )}
        </div>
        <button
          type="button"
          aria-label="Dismiss"
          className="rt-row-action -mr-1 rounded px-1 text-lg leading-none opacity-70 hover:opacity-100"
          onClick={() => onDismiss(toast.id)}
        >
          ×
        </button>
      </div>
    </div>
  );
}
