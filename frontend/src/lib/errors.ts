/** An API failure: the server's message plus its machine-readable code when it sent one. */
export class ApiError extends Error {
  status: number;
  code?: string;
  hint?: string;
  constructor(message: string, status: number, code?: string, hint?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.hint = hint;
  }
}

export interface ErrorAction {
  label: string;
  /** In-app route to open. */
  to?: string;
  /** External page to open. */
  href?: string;
}

export interface DescribedError {
  code: string;
  title: string;
  /** Plain-language explanation; the raw server text is kept in `raw`. */
  detail: string;
  action?: ErrorAction;
  raw: string;
}

interface Rule {
  code: string;
  match: RegExp;
  title: string;
  detail: (raw: string) => string;
  action?: ErrorAction;
}

const hostOf = (raw: string) =>
  raw.match(/https?:\/\/[^\s:/]+(?::\d+)?/)?.[0] ?? "the model server";

// Order matters: the first match wins, most specific first.
const RULES: Rule[] = [
  {
    code: "auth",
    match: /Session expired or missing/i,
    title: "Your session expired",
    detail: () =>
      "Reopen ResumeTailor from its window, or open the sign-in link printed when it started.",
  },
  {
    code: "soffice_missing",
    match: /LibreOffice binary not found|soffice.*not found/i,
    title: "PDF engine not found",
    detail: () =>
      "ResumeTailor uses LibreOffice to make PDFs and measure page fit. Install it, then try again.",
    action: { label: "Get LibreOffice", href: "https://www.libreoffice.org/download/download/" },
  },
  {
    code: "soffice_failed",
    match: /LibreOffice did not (finish|produce)/i,
    title: "The PDF could not be made",
    detail: () =>
      "LibreOffice stopped before finishing. Close any open LibreOffice windows and try again.",
  },
  {
    code: "model_missing",
    match: /has no model '([^']+)'/i,
    title: "That model is not installed",
    detail: (raw) => {
      const model = raw.match(/has no model '([^']+)'/i)?.[1] ?? "the model";
      return `Your model server does not have ${model}. In a terminal, run: ollama pull ${model}`;
    },
  },
  {
    code: "llm_unreachable",
    match: /Could not reach/i,
    title: "Can't reach the AI model",
    detail: (raw) =>
      `Nothing answered at ${hostOf(raw)}. If you use Ollama, make sure it is running, then try again.`,
    action: { label: "Model settings", to: "/settings" },
  },
  {
    code: "llm_auth",
    match:
      /No API key found|HTTP 401|HTTP 403|authentication_error|invalid x-api-key|API key not valid/i,
    title: "Your API key was rejected or is missing",
    detail: () =>
      "Check the key in Settings. Keys are stored in your system keychain, not in files.",
    action: { label: "Open Settings", to: "/settings" },
  },
  {
    code: "llm_quota",
    match: /HTTP 429|rate.?limit|credit balance|quota/i,
    title: "The AI provider is limiting requests",
    detail: () =>
      "You hit a rate limit or ran out of credit. Wait a minute, or check your provider account.",
  },
  {
    code: "llm_output",
    match: /token ceiling|did not return (valid )?.*JSON|Unreadable response/i,
    title: "The model's answer could not be used",
    detail: () =>
      "The model returned something incomplete. Try again, or choose a stronger model in Settings.",
  },
  {
    code: "template_missing",
    match: /main_template\.docx|template.*(not found|missing)|No template/i,
    title: "No resume template yet",
    detail: () => "Upload your resume (.docx) or pick a default template first.",
    action: { label: "Set up a template", to: "/template" },
  },
  {
    code: "overflow",
    match: /overflow|does not fit|too long for/i,
    title: "Your resume does not fit the page",
    detail: () =>
      "Even the shortest wording is too long. Remove an entry, lower the bullet count, or allow 2 pages.",
  },
  {
    code: "browser_disconnected",
    match: /connect_over_cdp|ECONNREFUSED.*9222|browser.*(not connected|closed)/i,
    title: "The browser is not connected",
    detail: () => "Start the automation browser (see the Apply page) and try again.",
    action: { label: "Open Apply", to: "/applications" },
  },
  {
    code: "busy",
    match: /is running; try again|in progress/i,
    title: "Busy with another task",
    detail: () => "Wait for the current run to finish, then try again.",
  },
  {
    code: "payload_too_large",
    match: /Request body is \d+ bytes|larger than 2 GB|Payload Too Large|HTTP 413/i,
    title: "File is too large",
    detail: (raw) =>
      /larger than 2 GB/i.test(raw)
        ? raw
        : /Request body is \d+ bytes/i.test(raw)
          ? "This file is larger than the 2 GB import limit."
          : raw || "This file is larger than the 2 GB import limit.",
  },
  {
    code: "network",
    match: /Failed to fetch|NetworkError|Load failed/i,
    title: "Can't reach ResumeTailor",
    detail: () =>
      "The app's local server is not responding. Make sure ResumeTailor is still running.",
  },
];

/** Plain-language title, explanation and next step for any thrown value or message. */
export function describe(error: unknown): DescribedError {
  const raw =
    error instanceof Error ? error.message : typeof error === "string" ? error : String(error);
  const code = error instanceof ApiError ? error.code : undefined;
  const is413 = error instanceof ApiError && error.status === 413;
  const rule =
    (code && RULES.find((r) => r.code === code)) ||
    (is413 && RULES.find((r) => r.code === "payload_too_large")) ||
    RULES.find((r) => r.match.test(raw));
  if (rule) {
    return {
      code: rule.code,
      title: rule.title,
      detail: rule.detail(raw),
      action: rule.action,
      raw,
    };
  }
  const hint = error instanceof ApiError ? error.hint : undefined;
  return { code: code ?? "unknown", title: "Something went wrong", detail: hint ?? raw, raw };
}
