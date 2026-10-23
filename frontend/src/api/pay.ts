import { apiError, request } from "./core";

export type PayCurrency = "USD" | "CAD" | "GBP" | "EUR" | "AUD";
export type PayPeriod = "hour" | "week" | "month" | "year";

/** A pay figure or range a posting states (`pay_parse.PostedRange`). */
export type PostedRange = {
  low: number;
  high: number;
  currency: PayCurrency;
  period: PayPeriod;
  /** False when the period came from the figure's size, not a word. */
  period_stated: boolean;
  excerpt: string;
};

/** One posting's range or one imported row, as the benchmark lists it. */
export type PayFigure = {
  low: number;
  high: number;
  company: string;
  role: string;
  location: string;
  on: string;
  source: string;
  excerpt: string;
  app_id: string;
  sample_size: number | null;
  median: number | null;
  currency: PayCurrency;
  period: PayPeriod;
};

/** Figures in one currency and period; percentiles only from five figures up. */
export type PaySplit = {
  currency: PayCurrency;
  period: PayPeriod;
  n: number;
  p25: number | null;
  median: number | null;
  p75: number | null;
  figures: PayFigure[];
};

export type PayGroup = {
  kind: "company" | "near" | "anywhere";
  label: string;
  n: number;
  sources: string[];
  first_on: string;
  last_on: string;
  splits: PaySplit[];
};

export type ApplicationPay = {
  posted: PostedRange[];
  family: string;
  level: string;
  groups: PayGroup[];
};

export type PayField =
  | "company"
  | "role"
  | "level"
  | "location"
  | "currency"
  | "period"
  | "low"
  | "high"
  | "median"
  | "sample_size"
  | "source"
  | "as_of";

export type PayPreview = {
  columns: string[];
  mapping: Record<PayField, string>;
  rows: string[][];
  total_rows: number;
};

export type PayDataset = {
  id: string;
  name: string;
  source: string;
  as_of: string;
  imported_at: string;
  row_count: number;
  rejected_count: number;
  rejected: { row: number; reason: string }[];
};

/** The posting's own range and posted ranges for similar roles. */
export function getApplicationPay(sourceJobId: string): Promise<ApplicationPay> {
  return request(`/api/applications/${encodeURIComponent(sourceJobId)}/pay`);
}

async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: "POST", body: form });
  if (!res.ok) throw await apiError(res);
  return (await res.json()) as T;
}

/** The file's columns and guessed mapping; nothing is saved. */
export function previewPayData(file: File): Promise<PayPreview> {
  const form = new FormData();
  form.append("file", file);
  return upload("/api/pay/datasets/preview", form);
}

/** Import the file with the confirmed column mapping. */
export function importPayData(
  file: File,
  mapping: Record<PayField, string>,
  meta: { name?: string; source?: string; as_of?: string },
): Promise<PayDataset> {
  const form = new FormData();
  form.append("file", file);
  form.append("mapping", JSON.stringify(mapping));
  for (const [key, value] of Object.entries(meta)) if (value) form.append(key, value);
  return upload("/api/pay/datasets", form);
}

export function listPayData(): Promise<PayDataset[]> {
  return request("/api/pay/datasets");
}

export function deletePayData(id: string): Promise<void> {
  return request(`/api/pay/datasets/${encodeURIComponent(id)}`, { method: "DELETE" });
}
