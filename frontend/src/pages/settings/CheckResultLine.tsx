import type { CheckResult } from "../../api";
import { describe } from "../../lib/errors";
import { StatusMark } from "../../components/ui";

/** Outcome of a "Test" button: green on success, the plain-language reason on failure. */
export function CheckResultLine({ result }: { result: CheckResult }) {
  if (result.ok) {
    return (
      <p role="status" className="mt-3 flex items-start gap-2 text-sm text-ink-2">
        <StatusMark tone="done" />
        <span>
          Working{result.model ? `: ${result.model}` : ""}. {result.detail}
        </span>
      </p>
    );
  }
  const d = describe(result.detail);
  return (
    <div role="alert" className="mt-3 text-sm text-danger">
      <p className="flex items-center gap-2 font-semibold">
        <StatusMark tone="failed" />
        {d.title}
      </p>
      <p className="mt-1 text-ink">{d.detail}</p>
      {d.raw !== d.detail && (
        <details className="mt-1 text-xs text-ink-muted">
          <summary className="cursor-pointer">Technical details</summary>
          <p className="mt-1 whitespace-pre-wrap break-words font-mono">{d.raw}</p>
        </details>
      )}
    </div>
  );
}
