import { useRef, useState } from "react";
import type { EvidenceSourceKind } from "../../../api";
import { Button, Segmented } from "../../../components/ui";
import { SOURCE_KIND_LABELS } from "../../../lib/evidence";

type Mode = "github" | "paste" | "file";
const DOCUMENT_KINDS: EvidenceSourceKind[] = ["writeup", "syllabus", "letter", "other"];

/** Add a source: GitHub (username or repository link), pasted text, or a file. */
export function AddSourceForm({
  githubUser,
  hasToken,
  busy,
  onGitHub,
  onText,
  onFile,
}: {
  githubUser: string;
  hasToken: boolean;
  busy: string | null;
  onGitHub: (target: string) => Promise<boolean>;
  onText: (kind: EvidenceSourceKind, title: string, text: string) => Promise<boolean>;
  onFile: (kind: EvidenceSourceKind, title: string, file: File) => Promise<boolean>;
}) {
  const [mode, setMode] = useState<Mode>("github");
  const [target, setTarget] = useState(githubUser);
  const [kind, setKind] = useState<EvidenceSourceKind>("writeup");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const adding = busy === "add-source";

  const reset = () => {
    setTitle("");
    setText("");
  };

  return (
    <div className="space-y-3">
      <Segmented
        label="Add from"
        value={mode}
        onChange={(id) => setMode(id as Mode)}
        items={[
          { id: "github", label: "GitHub" },
          { id: "paste", label: "Paste text" },
          { id: "file", label: "Upload a file" },
        ]}
      />
      {mode === "github" ? (
        <div className="space-y-2">
          <label className="block text-xs">
            <span className="font-medium">Username or repository link</span>
            <input
              className="field mt-1 w-full text-sm"
              value={target}
              placeholder="octocat or github.com/octocat/project"
              onChange={(e) => setTarget(e.target.value)}
            />
          </label>
          <p className="text-xs text-ink-muted">
            Lists up to 20 public repositories you own, newest first. Nothing is read for the resume
            until you scan one.
            {!hasToken &&
              " Without a GitHub token in Settings, GitHub allows about 20 repositories an hour."}
          </p>
          <Button
            size="sm"
            loading={busy === "github"}
            disabled={!target.trim() || busy !== null}
            onClick={() => void onGitHub(target.trim())}
          >
            List repositories
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block text-xs">
              <span className="font-medium">What it is</span>
              <select
                className="field mt-1 w-full text-sm"
                value={kind}
                onChange={(e) => setKind(e.target.value as EvidenceSourceKind)}
              >
                {DOCUMENT_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {SOURCE_KIND_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs">
              <span className="font-medium">Name (optional)</span>
              <input
                className="field mt-1 w-full text-sm"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
          </div>
          {mode === "paste" ? (
            <>
              <textarea
                className="field min-h-32 w-full text-sm"
                aria-label="Document text"
                placeholder="Paste the syllabus, letter or write-up"
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
              <Button
                size="sm"
                loading={adding}
                disabled={!text.trim() || busy !== null}
                onClick={() => void onText(kind, title, text).then((ok) => ok && reset())}
              >
                Add and scan
              </Button>
            </>
          ) : (
            <>
              <input
                ref={input}
                type="file"
                accept=".txt,.pdf,.docx"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void onFile(kind, title, file).then((ok) => ok && reset());
                }}
              />
              <Button
                size="sm"
                loading={adding}
                disabled={busy !== null}
                onClick={() => input.current?.click()}
              >
                Choose a .txt, .pdf or .docx…
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
