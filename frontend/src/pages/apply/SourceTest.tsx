import { useEffect, useRef, useState } from "react";
import { testSource, type SourceConfig, type SourceTestResult } from "../../api";
import { Button } from "../../components/ui";
import { describe } from "../../lib/errors";

const DROPPED_REASONS: Record<string, (result: SourceTestResult) => string> = {
  too_old: (r) => {
    const days = r.max_age_days ?? 0;
    return `older than ${days} day${days === 1 ? "" : "s"} (this list's limit or Apply settings)`;
  },
  title: () => "titles your profile rules out",
  citizenship: () => "needing US citizenship",
  advanced_degree: () => "needing an advanced degree",
  no_sponsorship: () => "with no visa sponsorship",
};

/** "Dropped: 593 older than 1 day (…), 2 needing US citizenship" - why found is not kept. */
function droppedNote(result: SourceTestResult): string {
  const parts = Object.entries(result.dropped ?? {})
    .filter(([, n]) => n > 0)
    .map(
      ([reason, n]) =>
        `${n.toLocaleString("en-US")} ${DROPPED_REASONS[reason]?.(result) ?? reason}`,
    );
  return parts.length ? `Dropped: ${parts.join(", ")}.` : "";
}

/** Test result panel: counts, up to five sample rows and any per-source errors. */
export function SourceTestPanel({
  result,
  error,
  loading,
}: {
  result: SourceTestResult | null;
  error: string;
  loading: boolean;
}) {
  if (loading)
    return (
      <p role="status" className="mt-2 text-xs text-ink-muted">
        Reading the source…
      </p>
    );
  if (error)
    return (
      <p role="alert" className="mt-2 rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
        Test failed: {error}
      </p>
    );
  if (!result) return null;
  return (
    <div
      role="region"
      aria-label="Test result"
      className="mt-2 space-y-2 rounded-md border border-line bg-paper p-3 text-xs"
    >
      <p className="font-medium" aria-live="polite">
        {result.rows_total} posting{result.rows_total === 1 ? "" : "s"} found · {result.rows_kept}{" "}
        would be kept by your filters
      </p>
      {droppedNote(result) && <p className="text-ink-muted">{droppedNote(result)}</p>}
      {result.errors.length > 0 && (
        <ul role="alert" className="list-disc space-y-0.5 pl-4 text-danger">
          {result.errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      {result.sample.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] text-left">
            <caption className="sr-only">Sample postings</caption>
            <thead className="text-ink-muted">
              <tr>
                <th scope="col" className="py-1 pr-2 font-medium">
                  Company
                </th>
                <th scope="col" className="py-1 pr-2 font-medium">
                  Role
                </th>
                <th scope="col" className="py-1 pr-2 font-medium">
                  Location
                </th>
                <th scope="col" className="py-1 font-medium">
                  Posted
                </th>
              </tr>
            </thead>
            <tbody>
              {result.sample.map((row, i) => (
                <tr key={`${row.company}-${row.role}-${i}`} className="border-t border-line">
                  <td className="py-1 pr-2">{row.company}</td>
                  <td className="py-1 pr-2">
                    {row.application_link ? (
                      <a
                        className="text-accent underline"
                        href={row.application_link}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {row.role}
                      </a>
                    ) : (
                      row.role
                    )}
                  </td>
                  <td className="py-1 pr-2">{row.location}</td>
                  <td className="py-1">{row.age || row.posted_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        result.errors.length === 0 && (
          <p className="text-ink-muted">
            Nothing matched. Check the categories, title filters and posting age.
          </p>
        )
      )}
    </div>
  );
}

/** Runs one source once (no LLM, nothing saved) and keeps the latest result. */
export function useSourceTest() {
  const [result, setResult] = useState<SourceTestResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function run(source: SourceConfig) {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      setResult(await testSource(source));
    } catch (reason) {
      setError(describe(reason).detail);
    } finally {
      setLoading(false);
    }
  }

  const reset = () => {
    setResult(null);
    setError("");
  };
  return { result, error, loading, run, reset };
}

/**
 * A Test button plus its result panel, for one source. ``autoRun`` also runs it once when
 * it first appears (the edit panel), unless ``disabled``; edits after that need Test again.
 */
export function SourceTest({
  source,
  disabled,
  autoRun,
}: {
  source: SourceConfig;
  disabled?: boolean;
  autoRun?: boolean;
}) {
  const test = useSourceTest();
  const ran = useRef(false);
  useEffect(() => {
    if (!autoRun || disabled || ran.current) return;
    ran.current = true;
    void test.run(source);
    // Once per mount: the source object changes on every keystroke in the panel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div>
      <Button
        size="sm"
        variant="secondary"
        disabled={disabled}
        loading={test.loading}
        onClick={() => void test.run(source)}
      >
        Test
      </Button>
      <SourceTestPanel result={test.result} error={test.error} loading={test.loading} />
    </div>
  );
}
