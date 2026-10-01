/** Fetch plumbing shared by every API module: JSON requests, error bodies, ETag polling. */

import { ApiError } from "../lib/errors";

/** The thrown error for a failed response: FastAPI's `detail`, plus `error`/`hint` codes. */
export async function apiError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  let code: string | undefined;
  let hint: string | undefined;
  try {
    const body = await res.json();
    detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    code = typeof body.error === "string" ? body.error : undefined;
    hint = typeof body.hint === "string" ? body.hint : undefined;
  } catch {
    /* keep statusText */
  }
  return new ApiError(detail, res.status, code, hint);
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  /** JSON fetch that surfaces FastAPI error bodies as thrown Errors. */
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) throw await apiError(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Last body and ETag per URL, for `conditionalGet`. */
const etagCache = new Map<string, { etag: string; body: unknown }>();

/**
 * GET that sends `If-None-Match` and, on a 304, returns the very object it returned
 * last time: a poll that finds nothing new hands React the same reference, so the
 * table does not re-render.
 */
export async function conditionalGet<T>(path: string): Promise<T> {
  const cached = etagCache.get(path);
  const res = await fetch(path, {
    headers: cached ? { "If-None-Match": cached.etag } : {},
  });
  if (res.status === 304 && cached) return cached.body as T;
  if (!res.ok) throw await apiError(res);
  const body = (await res.json()) as T;
  const etag = res.headers.get("ETag");
  if (etag) {
    if (etagCache.size > 50) etagCache.clear();
    etagCache.set(path, { etag, body });
  }
  return body;
}

/**
 * Parse a FastAPI error body from a template upload/analyze response.
 */
export async function templateErrorDetail(res: Response): Promise<string> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") {
      detail = d;
    } else if (d && typeof d === "object" && "message" in d) {
      const msg = String((d as { message: string }).message);
      const log = String((d as { log?: string }).log ?? "");
      detail = log ? `${msg}\n\n${log}` : msg;
    } else {
      detail = JSON.stringify(d ?? body);
    }
  } catch {
    /* keep statusText */
  }
  return detail;
}
