import { useRef, useState } from "react";
import { extractJdFile, fetchJdFromUrl, type JdText } from "../../api";
import { Tabs } from "../../components/Tabs";
import { Button } from "../../components/ui";
import { describe } from "../../lib/errors";
import { hostOf, JD_FILE_ACCEPT, wordCount } from "../../lib/jdInput";

type Mode = "paste" | "url" | "file";

/**
 * The job posting, three ways: paste it, fetch it from a link, or read it from a
 * file. Fetching and reading only fill the text box; the student checks the text
 * before tailoring, so a bad extraction is visible rather than silently used.
 */
export function JobInput({
  jdText,
  setJdText,
  disabled,
}: {
  jdText: string;
  setJdText: (text: string) => void;
  disabled: boolean;
}) {
  const [mode, setMode] = useState<Mode>("paste");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [origin, setOrigin] = useState<{ label: string; warnings: string[] } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function accept(result: JdText, label: string) {
    setJdText(result.text);
    setOrigin({ label, warnings: result.warnings });
    setMode("paste");
  }

  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (err) {
      setError(describe(err).detail);
    } finally {
      setBusy(false);
    }
  }

  const fetchUrl = () =>
    run(async () => {
      const result = await fetchJdFromUrl(url.trim());
      accept(result, `Fetched from ${hostOf(result.final_url || url)}`);
    });

  const readFile = (file: File | null) => {
    if (!file) return;
    void run(async () => accept(await extractJdFile(file), `Read from ${file.name}`));
    if (fileRef.current) fileRef.current.value = "";
  };

  const words = wordCount(jdText);

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm lg:col-start-1 lg:row-start-2">
      <h2 className="mb-3 font-display text-xl font-semibold">Job description</h2>
      <Tabs
        label="How to add the job description"
        items={[
          { id: "paste", label: "Paste text" },
          { id: "url", label: "From a link" },
          { id: "file", label: "Upload a file" },
        ]}
        value={mode}
        onChange={(id) => {
          setMode(id as Mode);
          setError(null);
        }}
      />
      <div role="tabpanel" className="mt-3">
        {mode === "url" && (
          <div className="space-y-2">
            <label className="block text-sm text-ink-muted" htmlFor="jd-url">
              Link to the posting (Greenhouse, Lever, Ashby, Workday, company career pages…)
            </label>
            <div className="flex flex-wrap gap-2">
              <input
                id="jd-url"
                type="url"
                inputMode="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && url.trim()) {
                    e.preventDefault();
                    void fetchUrl();
                  }
                }}
                placeholder="https://…"
                className="field min-w-0 flex-1"
                disabled={disabled || busy}
              />
              <Button
                variant="primary"
                onClick={() => void fetchUrl()}
                disabled={disabled || !url.trim()}
                loading={busy}
              >
                {busy ? "Reading…" : "Get posting"}
              </Button>
            </div>
            <p className="text-xs text-ink-muted">
              LinkedIn and Handshake need you signed in, so copy and paste from those instead.
            </p>
          </div>
        )}
        {mode === "file" && (
          <div className="rounded-lg border border-dashed border-line bg-paper/40 p-6 text-center text-sm">
            <p className="text-ink-muted">A saved posting: .pdf, .docx, .txt or .html</p>
            <Button
              className="mt-3"
              onClick={() => fileRef.current?.click()}
              disabled={disabled}
              loading={busy}
            >
              {busy ? "Reading…" : "Choose file"}
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept={JD_FILE_ACCEPT}
              className="hidden"
              onChange={(e) => readFile(e.target.files?.[0] ?? null)}
            />
          </div>
        )}
        {mode === "paste" && (
          <>
            {origin && (
              <div className="mb-2 rounded-md bg-accent-soft/60 px-3 py-2 text-xs text-ink">
                <p>
                  <strong>{origin.label}.</strong> Check the text below, then tailor.
                </p>
                {origin.warnings.map((w) => (
                  <p key={w} className="mt-1 text-warn">
                    {w}
                  </p>
                ))}
              </div>
            )}
            <textarea
              aria-label="Job description text"
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              rows={14}
              placeholder="Paste the posting here…"
              className="w-full resize-y rounded-lg border border-line bg-paper/40 px-3 py-2 text-sm leading-relaxed focus:border-accent"
              required
            />
            <p className="mt-1 text-right text-xs text-ink-muted tabular-nums">
              {words > 0 ? `${words.toLocaleString()} words` : ""}
              {words > 0 && words < 60 ? " · that looks short for a full posting" : ""}
            </p>
          </>
        )}
        {error && (
          <p role="alert" className="mt-2 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
