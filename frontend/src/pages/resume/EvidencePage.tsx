import { useState } from "react";
import { Link } from "react-router-dom";
import type { EvidenceProposal } from "../../api";
import { CommandBar, Page, Tile } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useEvidence } from "../../lib/useEvidence";
import { useEditorState } from "../../state/editorState";
import { AddEvidenceDialog } from "./evidence/AddEvidenceDialog";
import { AddSourceForm } from "./evidence/AddSourceForm";
import { ProposalList } from "./evidence/ProposalList";
import { SourceList } from "./evidence/SourceList";

/**
 * Evidence: GitHub repositories and documents the student adds, and the resume items read
 * from them. Each item quotes its source and changes nothing until the student adds it,
 * keeps a skill for matching only, or dismisses it.
 */
export function EvidencePage() {
  const toast = useToast();
  const editor = useEditorState();
  const evidence = useEvidence((resume) => editor.syncFromDisk(resume, "Added from evidence."));
  const [adding, setAdding] = useState<EvidenceProposal | null>(null);
  const { view, busy } = evidence;

  const run = async (action: () => Promise<unknown>, failed: string) => {
    try {
      await action();
      return true;
    } catch (reason) {
      toast.error(failed, describe(reason).detail);
      return false;
    }
  };
  const addBlocked = editor.dirty ? "Save or discard your resume edits first." : "";
  const pending = view?.proposals.filter((p) => p.state === "pending").length ?? 0;

  return (
    <Page className="pb-4">
      <CommandBar
        title="Evidence"
        back={
          <Link className="rt-link" to="/resume">
            Resume
          </Link>
        }
        state={
          view
            ? `${view.sources.length} ${view.sources.length === 1 ? "source" : "sources"} · ${pending} waiting`
            : undefined
        }
      />
      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
        <div className="space-y-5">
          <Tile title="Add a source">
            {view && (
              <AddSourceForm
                githubUser={view.github_user}
                hasToken={view.github_token}
                busy={busy}
                onGitHub={(target) =>
                  run(async () => {
                    const next = await evidence.addGitHub(target);
                    for (const warning of next.warnings) toast.info(warning);
                  }, "Could not read GitHub")
                }
                onText={(kind, title, text) =>
                  run(() => evidence.addText(kind, title, text), "Could not add that")
                }
                onFile={(kind, title, file) =>
                  run(() => evidence.addFile(kind, title, file), "Could not read the file")
                }
              />
            )}
          </Tile>
          <Tile title="Sources">
            {view ? (
              <SourceList
                sources={view.sources}
                busy={busy}
                onScan={(source) =>
                  void run(() => evidence.scan(source.id), `Could not scan ${source.title}`)
                }
                onRemove={(source) =>
                  void run(() => evidence.removeSource(source.id), "Could not remove")
                }
              />
            ) : (
              <p className="text-sm text-ink-muted">
                {evidence.loadError ? describe(evidence.loadError).detail : "Loading…"}
              </p>
            )}
          </Tile>
        </div>
        <Tile title="Could go on your resume">
          <p className="mb-3 text-xs text-ink-muted">
            Each item quotes its source. Nothing changes your resume until you add it; a skill kept
            for matching only helps match postings and is never printed.
          </p>
          {view && (
            <ProposalList
              sources={view.sources}
              proposals={view.proposals}
              resume={editor.resume}
              evidence={evidence}
              addBlocked={addBlocked}
              onAdd={setAdding}
              run={(action, failed) => void run(action, failed)}
            />
          )}
        </Tile>
      </div>
      {adding && view && (
        <AddEvidenceDialog
          proposal={adding}
          source={view.sources.find((s) => s.id === adding.source_id)}
          resume={editor.resume}
          busy={busy === adding.id}
          onClose={() => setAdding(null)}
          onSave={(body) =>
            void run(() => evidence.add(adding.id, body), "Could not add it").then((ok) => {
              if (!ok) return;
              setAdding(null);
              toast.success("Added to your resume");
            })
          }
        />
      )}
    </Page>
  );
}
