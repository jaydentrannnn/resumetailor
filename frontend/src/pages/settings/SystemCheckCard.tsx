import { useState } from "react";
import { testModel, testPdf, type CheckResult } from "../../api";
import { Button, Card } from "../../components/ui";
import { emitAppEvent } from "../../lib/appEvents";
import { describe } from "../../lib/errors";
import { useRunState } from "../../state/runState";
import { CheckResultLine } from "./CheckResultLine";

const ENGINE_NAMES: Record<string, string> = { soffice: "LibreOffice", word: "Microsoft Word" };
const CHECKS = [
  { id: "tailor", label: "Tailoring model" },
  { id: "autofill", label: "Autofill model" },
  { id: "pdf", label: "PDF conversion" },
] as const;
type CheckId = (typeof CHECKS)[number]["id"];

async function settle(call: () => Promise<CheckResult>): Promise<CheckResult> {
  try {
    return await call();
  } catch (err) {
    return { ok: false, detail: describe(err).detail };
  }
}

/** One button that checks everything a run needs: both models and the PDF engine. */
export function SystemCheckCard() {
  const { config, settings } = useRunState();
  const [results, setResults] = useState<Partial<Record<CheckId, CheckResult>> | null>(null);
  const [running, setRunning] = useState(false);
  const engine = config?.pdf_backend ?? "";

  async function run() {
    setRunning(true);
    setResults(null);
    const [tailor, autofill, pdf] = await Promise.all([
      settle(() => testModel(settings, "tailor")),
      settle(() => testModel(settings, "autofill")),
      settle(testPdf),
    ]);
    setResults({ tailor, autofill, pdf });
    setRunning(false);
    emitAppEvent("rt:setup-changed");
  }

  return (
    <Card
      title="System check"
      description={`Tests both AI models and PDF conversion (${ENGINE_NAMES[engine] ?? engine}). Each model test sends one tiny request.`}
      actions={
        <Button variant="secondary" loading={running} onClick={() => void run()}>
          Run system check
        </Button>
      }
    >
      {results ? (
        <ul className="space-y-3">
          {CHECKS.map((check) => (
            <li key={check.id}>
              <p className="text-sm font-medium">{check.label}</p>
              {results[check.id] && <CheckResultLine result={results[check.id]!} />}
              {check.id === "pdf" && engine === "soffice" && !results.pdf?.ok && (
                <a
                  className="rt-link mt-1 inline-block text-sm"
                  href="https://www.libreoffice.org/download/download/"
                  target="_blank"
                  rel="noreferrer"
                >
                  Get LibreOffice (free)
                </a>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-muted">
          Run it if a resume fails to generate or after installing something new.
        </p>
      )}
    </Card>
  );
}
