import { createContext, useContext } from "react";

export type ToastKind = "success" | "error" | "info";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
  action?: ToastAction;
  /** Milliseconds before it closes itself; null stays until dismissed. */
  timeoutMs: number | null;
}

export type ToastInput = Omit<Toast, "id" | "timeoutMs"> & { timeoutMs?: number | null };

/** Errors stay until dismissed (a user must be able to read them); others clear in 5 s. */
export function defaultTimeout(kind: ToastKind): number | null {
  return kind === "error" ? null : 5000;
}

export const MAX_TOASTS = 4;

export type ToastEvent = { type: "push"; toast: Toast } | { type: "dismiss"; id: number };

/** Newest last; an identical title+detail replaces its older copy instead of stacking. */
export function toastReducer(state: Toast[], event: ToastEvent): Toast[] {
  if (event.type === "dismiss") return state.filter((t) => t.id !== event.id);
  const rest = state.filter(
    (t) => !(t.title === event.toast.title && t.detail === event.toast.detail),
  );
  return [...rest, event.toast].slice(-MAX_TOASTS);
}

export interface ToastApi {
  show: (toast: ToastInput) => number;
  success: (title: string, detail?: string, action?: ToastAction) => number;
  error: (title: string, detail?: string, action?: ToastAction) => number;
  info: (title: string, detail?: string, action?: ToastAction) => number;
  dismiss: (id: number) => void;
}

const noop: ToastApi = {
  show: () => 0,
  success: () => 0,
  error: () => 0,
  info: () => 0,
  dismiss: () => {},
};

export const ToastContext = createContext<ToastApi>(noop);

/** Toasts from anywhere under `ToastProvider`; a no-op outside one (tests, isolated renders). */
export function useToast(): ToastApi {
  return useContext(ToastContext);
}
