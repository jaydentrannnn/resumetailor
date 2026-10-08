import { SettingRow } from "./SettingRow";
import { buttonClass } from "../../lib/buttonClass";
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
    <div className="space-y-4">
      <Card
        title="PDF engine"
        description="Makes the PDF of your resume and measures how much fits on a page."
      >
        <SettingRow
          label="Conversion"
          description={
            <>
              Using <strong>{ENGINE_NAMES[engine] ?? engine}</strong>.
              {engine === "soffice" && " LibreOffice is free; install it if the test below fails."}
            </>
          }
        >
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" onClick={run} loading={testing}>
              Test PDF conversion
            </Button>
            {engine === "soffice" && (
              <a
                className="rt-link text-sm font-medium"
                href="https://www.libreoffice.org/download/download/"
                target="_blank"
                rel="noreferrer"
              >
                Get LibreOffice
              </a>
            )}
          </div>
        </SettingRow>
        {result && <CheckResultLine result={result} />}
      </Card>
      <Card
        title="Page fit"
        description="ResumeTailor measures your template once so tailored resumes fill the page without spilling over."
      >
        <SettingRow
          label="Calibration"
          description={
            calibrated
              ? `Tuned for your template (${config?.chars_per_line} characters per line, ${config?.lines_per_page} lines per page).`
              : "Using estimates. Tune it once from the Template page for exact page fit."
          }
        >
          <Link to="/template" className={buttonClass("secondary", "md")}>
            Open Template
          </Link>
        </SettingRow>
      </Card>
    </div>
  );
}
