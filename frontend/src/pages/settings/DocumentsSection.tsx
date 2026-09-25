import { useState } from "react";
import { Link } from "react-router-dom";
import { testPdf, type CheckResult } from "../../api";
import { Button, Card } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useRunState } from "../../state/runState";
import { CheckResultLine } from "./CheckResultLine";

const ENGINE_NAMES: Record<string, string> = {
  soffice: "LibreOffice",
  word: "Microsoft Word",
};

/** Settings → Documents: the PDF engine and page-fit tuning. */
export function DocumentsSection() {
  const { config } = useRunState();
  const [result, setResult] = useState<CheckResult | null>(null);
  const [testing, setTesting] = useState(false);
  const engine = config?.pdf_backend ?? "";
  const calibrated = config ? config.calibration_source !== "fallback" : false;

  async function run() {
    setTesting(true);
    setResult(null);
    try {
      setResult(await testPdf());
    } catch (err) {
      setResult({ ok: false, detail: describe(err).raw });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card
        title="PDF engine"
        description="Makes the PDF of your resume and measures how much fits on a page."
      >
        <p className="text-sm text-ink">
          Using <strong>{ENGINE_NAMES[engine] ?? engine}</strong>.
          {engine === "soffice" && " LibreOffice is free; install it if the test below fails."}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={run} loading={testing}>
            Test PDF conversion
          </Button>
          {engine === "soffice" && (
            <a
              className="text-sm font-medium text-accent underline-offset-2 hover:underline"
              href="https://www.libreoffice.org/download/download/"
              target="_blank"
              rel="noreferrer"
            >
              Get LibreOffice
            </a>
          )}
        </div>
        {result && <CheckResultLine result={result} />}
      </Card>
      <Card
        title="Page fit"
        description="ResumeTailor measures your template once so tailored resumes fill the page without spilling over."
      >
        <p className="text-sm text-ink">
          {calibrated
            ? `Tuned for your template (${config?.chars_per_line} characters per line, ${config?.lines_per_page} lines per page).`
            : "Using estimates. Tune it once from the Template page for exact page fit."}
        </p>
        <Link
          to="/template"
          className="mt-2 inline-block text-sm font-medium text-accent underline-offset-2 hover:underline"
        >
          Open Template
        </Link>
      </Card>
    </div>
  );
}
