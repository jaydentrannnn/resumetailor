import type { TemplateAnalyzeResponse } from "../../api";
import { issueHelp } from "../../lib/templateIssues";

type Issue = TemplateAnalyzeResponse["issues"][number];

/**
 * Analyzer findings in plain language: what it means, how to fix it in Word or Google
 * Docs, and the analyzer's exact wording under "Details" for anyone who wants it.
 */
export function IssueList({ issues, tone }: { issues: Issue[]; tone: "danger" | "warn" }) {
  const box = tone === "danger" ? "bg-danger-soft text-danger" : "bg-warn-soft text-warn";
  return (
    <div className={`rounded-md px-3 py-2 ${box}`}>
      <p className="font-semibold">
        {tone === "danger" ? "Needs fixing before install" : "Worth knowing"}
      </p>
      <ul className="mt-2 space-y-3">
        {issues.map((issue) => {
          const help = issueHelp(issue.code);
          return (
            <li key={issue.code + issue.message} className="text-ink">
              <p className="font-medium">{help.title}</p>
              <p className="text-ink-muted">{help.why}</p>
              {(help.word || help.docs || help.app) && (
                <dl className="mt-1 space-y-0.5 text-xs">
                  {help.word && (
                    <div>
                      <dt className="inline font-semibold">In Word: </dt>
                      <dd className="inline">{help.word}</dd>
                    </div>
                  )}
                  {help.docs && (
                    <div>
                      <dt className="inline font-semibold">In Google Docs: </dt>
                      <dd className="inline">{help.docs}</dd>
                    </div>
                  )}
                  {help.app && (
                    <div>
                      <dt className="inline font-semibold">Here: </dt>
                      <dd className="inline">{help.app}</dd>
                    </div>
                  )}
                </dl>
              )}
              <details className="mt-1 text-xs text-ink-muted">
                <summary className="cursor-pointer">Details</summary>
                <p className="mt-1 font-mono">
                  {issue.code}: {issue.message}
                </p>
              </details>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
