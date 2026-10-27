import { type ReactNode, useEffect, useRef, useState } from "react";
import { extractJdFile, fetchJdFromUrl, type JdText } from "../../api";
import { Tabs } from "../../components/Tabs";
import { Button, Tile } from "../../components/ui";
import { describe } from "../../lib/errors";
import { hostOf, JD_FILE_ACCEPT, wordCount } from "../../lib/jdInput";

type Mode = "paste" | "url" | "file";

/**
 * The job posting, three ways: paste it, fetch it from a link, or read it from a
 * file. Fetching and reading only fill the text box; the student checks the text
 * before tailoring, so a bad extraction is visible rather than silently used. A file
 * dropped anywhere on the tile is read the same way. Switching the way, or leaving the
 * page, cancels a fetch still running, so a late answer never replaces the text.
 * `footer` (the cost estimate) closes the tile.
 */
export function JobInput({
  jdText,
  setJdText,
  disabled,
  footer,
}: {
  jdText: string;
  setJdText: (text: string) => void;
  disabled: boolean;
  footer?: ReactNode;
}) {
  const [mode, setMode] = useState<Mode>("paste");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [origin, setOrigin] = useState<{ label: string; warnings: string[] } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);

  function cancelPending() {
    pending.current?.abort();
    pending.current = null;
    setBusy(false);
  }

  /** Run one fetch or read; it fills the text box only if it is still the current one. */
  async function run(task: (signal: AbortSignal) => Promise<JdText>, label: (r: JdText) => string) {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError(null);
    try {
      const result = await task(controller.signal);
      if (controller.signal.aborted) return;
      setJdText(result.text);
      setOrigin({ label: label(result), warnings: result.warnings });
      setMode("paste");
    } catch (err) {
      if (!controller.signal.aborted) setError(describe(err).detail);
    } finally {
      if (pending.current === controller) {
        pending.current = null;
        setBusy(false);
      }
    }
  }

  const fetchUrl = () =>
    run(
      (signal) => fetchJdFromUrl(url.trim(), signal),
      (result) => `Fetched from ${hostOf(result.final_url || url)}`,
    );

  const readFile = (file: File | null) => {
    if (!file) return;
    void run(
      (signal) => extractJdFile(file, signal),
      () => `Read from ${file.name}`,
    );
    if (fileRef.current) fileRef.current.value = "";
  };

  const words = wordCount(jdText);

  return (
    <div
      data-dropzone
      onDragOver={(e) => {
        if (!disabled && e.dataTransfer.types.includes("Files")) e.preventDefault();
      }}
      onDrop={(e) => {
        const file = e.dataTransfer.files?.[0];
        if (disabled || !file) return;
        e.preventDefault();
        readFile(file);
      }}
    >
      <Tile title="Job description">
        <Tabs
          variant="segmented"
          label="How to add the job description"
          items={[
            { id: "paste", label: "Paste text" },
            { id: "url", label: "From a link" },
            { id: "file", label: "Upload a file" },
          ]}
          value={mode}
          onChange={(id) => {
            cancelPending();
            setMode(id as Mode);
            setError(null);
          }}
        />
        <div role="tabpanel" className="mt-3">
          {mode === "url" && (
            <div className="space-y-2">
              <label className="block text-xs font-medium text-ink-2" htmlFor="jd-url">
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
                  onClick={() => void fetchUrl()}
                  disabled={disabled || busy || !url.trim()}
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
            <div className="flex flex-wrap items-center gap-3 py-2 text-sm">
              <Button onClick={() => fileRef.current?.click()} disabled={disabled} loading={busy}>
                {busy ? "Reading…" : "Choose file"}
              </Button>
              <p className="text-ink-muted">
                A saved posting: .pdf, .docx, .txt or .html. You can also drop it here.
              </p>
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
                <div className="mb-2 text-xs text-ink-2">
                  <p>
                    <strong>{origin.label}.</strong> Check the text below, then tailor.
                  </p>
                  {origin.warnings.map((w) => (
                    <p key={w} className="mt-1 text-attn">
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
                className="field resize-y text-sm leading-relaxed"
                required
              />
              <p className="mt-1 text-right font-mono text-xs text-ink-muted tabular-nums">
                {words > 0 ? `${words.toLocaleString()} words` : ""}
                {words > 0 && words < 60 ? " · that looks short for a full posting" : ""}
              </p>
            </>
          )}
          {error && (
            <p
              role="alert"
              className="mt-2 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger"
            >
              {error}
            </p>
          )}
        </div>
        {footer && <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">{footer}</div>}
      </Tile>
    </div>
  );
}
