import { EntryEditorProvider } from "./EntryEditorContext";
import { moveEntryToSection } from "../../lib/resumeEntryEdit";
import { useState } from "react";
import { Modal } from "../../components/Modal";
import { ResumeHistoryList } from "../../components/ResumeHistoryList";
import { ImportResumePanel } from "../../components/ImportResumePanel";
import { BulletSkillsProvider } from "../../state/bulletSkillsState";
import { BulletSkillsNotice } from "./BulletSkillsNotice";
import { useConfirm } from "../../state/confirmState";
import { useEditorState } from "../../state/editorState";
import { AddSectionPanel, SectionShell } from "./SectionShell";
import { ContactSection } from "./ContactSection";
import { SectionIndex } from "./SectionIndex";
import { EntryFilterField } from "./EntryFilterField";
import { useResumeUndo } from "./useResumeUndo";
import { Button, CommandBar, StatusMark, Tile } from "../../components/ui";
import { sectionMatches } from "../../lib/entryFilter";
import {
  type Section,
  type SectionKind,
  blankSection,
  collectBulletIds,
  collectEntryIds,
  collectSectionIds,
  moveItem,
  nextSectionId,
  removeAt,
} from "../../lib/resumeEdit";

/**
 * Structured editor for data/master_resume.json — validates through the real Pydantic models.
 *
 * Draft state lives in `EditorProvider` so unsaved edits survive a switch to the Tailor tab.
 * Sections are an ordered, arbitrary-length list (`resume.sections`) — any number of
 * experience-like, project-like, plain-list, education, or skills sections, in any order,
 * under any title. This page never assumes exactly one of each kind.
 */
export function EditorPage({
  showContact = true,
  embedded = false,
}: {
  showContact?: boolean;
  /** Inside setup, whose own flow saves: no command bar or Save button. */
  embedded?: boolean;
}) {
  const {
    resume,
    setResume: setDraft,
    config,
    errors,
    message,
    busy,
    dirty,
    validate: onValidate,
    save: onSave,
    discard,
  } = useEditorState();
  const { confirm } = useConfirm();
  const { edit: setResume, pushUndo, clear: clearUndo } = useResumeUndo(resume, setDraft);
  const [filter, setFilter] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);

  async function discardAll() {
    const ok = await confirm({
      title: "Discard unsaved changes?",
      message: "Your resume goes back to what was last saved.",
      confirmLabel: "Discard",
      tone: "danger",
    });
    if (ok) {
      discard();
      clearUndo();
    }
  }

  const vocabList = [...(config?.tag_vocabulary ?? [])].sort((a, b) =>
    a.toLowerCase().localeCompare(b.toLowerCase()),
  );

  const takenBulletIds = resume ? collectBulletIds(resume) : new Set<string>();
  const takenEntryIds = resume ? collectEntryIds(resume) : new Set<string>();

  if (!resume) {
    return (
      <p className="text-sm text-ink-muted">
        {errors.length ? errors.join("; ") : "Loading master resume…"}
      </p>
    );
  }

  function updateSection(index: number, next: Section) {
    setResume((prev) => {
      const sections = [...prev.sections];
      sections[index] = next;
      return { ...prev, sections };
    });
  }

  function addSection(kind: SectionKind, title: string) {
    setFilter("");
    setResume((prev) => {
      const id = nextSectionId(title, kind, collectSectionIds(prev));
      return { ...prev, sections: [...prev.sections, blankSection(id, kind, title)] };
    });
    // The new section is last; bring it into view once it renders.
    requestAnimationFrame(() =>
      document
        .querySelector("[data-resume-section]:last-of-type")
        ?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }

  function moveEntry(sourceId: string, key: string, destinationId: string) {
    const current = resume;
    if (!current || moveEntryToSection(current, sourceId, key, destinationId) === current) return;
    const destination = current.sections.find((section) => section.id === destinationId);
    pushUndo(`Moved entry to “${destination?.title || "section"}”`);
    setResume((previous) => moveEntryToSection(previous, sourceId, key, destinationId));
  }

  const tools = (
    <>
      <Button variant="plain" size="sm" onClick={() => setHistoryOpen(true)}>
        History
      </Button>
      <Button variant="plain" size="sm" onClick={onValidate} disabled={busy}>
        Validate
      </Button>
    </>
  );

  return (
    <EntryEditorProvider sections={resume.sections} moveEntry={moveEntry} filter={filter}>
      <BulletSkillsProvider dirty={dirty}>
        <div className="space-y-6">
          {embedded ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-muted">
                The skills each bullet shows are worked out automatically when you save.
              </p>
              <div className="flex flex-wrap items-center gap-2">{tools}</div>
            </div>
          ) : (
            <CommandBar
              title="Resume"
              state={
                <span className="flex items-center gap-1.5">
                  <StatusMark tone={dirty ? "attention" : "done"} />
                  {dirty ? "Unsaved changes" : "All changes saved"}
                </span>
              }
              actions={
                <>
                  {tools}
                  {dirty && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() => void discardAll()}
                    >
                      Discard
                    </Button>
                  )}
                  <Button
                    variant="primary"
                    size="sm"
                    data-shortcut="save"
                    onClick={onSave}
                    disabled={busy}
                  >
                    Save
                  </Button>
                </>
              }
            />
          )}
          <div>
            <BulletSkillsNotice />
            {message && (
              <p
                role="status"
                aria-live="polite"
                className="max-h-32 overflow-y-auto text-sm text-ink-muted"
              >
                {message}
              </p>
            )}
            {errors.length > 0 && (
              <ul role="alert" className="max-h-32 overflow-y-auto text-sm text-danger">
                {errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:items-start lg:gap-5">
            <SectionIndex sections={resume.sections} />
            <div className="space-y-5">
              <EntryFilterField value={filter} onChange={setFilter} />
              {filter && !resume.sections.some((section) => sectionMatches(section, filter)) && (
                <p className="text-sm text-ink-muted">No entries match “{filter}”.</p>
              )}
              {!filter && (
                <Tile>
                  <details>
                    <summary className="cursor-pointer text-sm font-medium text-accent">
                      Import resume content
                    </summary>
                    <div className="mt-3">
                      <ImportResumePanel embedded />
                    </div>
                  </details>
                </Tile>
              )}

              {showContact && !filter && <ContactSection resume={resume} setResume={setResume} />}

              {resume.sections.map((section, i) => (
                <div
                  key={section.id}
                  id={`resume-section-${section.id}`}
                  data-resume-section
                  hidden={!!filter && !sectionMatches(section, filter)}
                  className="scroll-mt-[calc(var(--rt-bar-top)+1rem)]"
                >
                  <SectionShell
                    key={section.id}
                    section={section}
                    index={i}
                    total={resume.sections.length}
                    vocabList={vocabList}
                    takenBulletIds={takenBulletIds}
                    takenEntryIds={takenEntryIds}
                    pushUndo={pushUndo}
                    onRemove={(idx) => {
                      const removedTitle = resume.sections[idx]?.title || "section";
                      pushUndo(`Removed “${removedTitle}”`);
                      setResume((prev) => ({ ...prev, sections: removeAt(prev.sections, idx) }));
                    }}
                    onMove={(from, to) =>
                      setResume((prev) => ({
                        ...prev,
                        sections: moveItem(prev.sections, from, to),
                      }))
                    }
                    onChange={(next) => updateSection(i, next)}
                  />
                </div>
              ))}
            </div>
          </div>

          <p className="text-xs text-ink-muted">
            Reordering sections changes bullet scoring order — the next Tailor run will re-score
            once (one extra LLM call) before using the new order.
          </p>

          <AddSectionPanel onAdd={addSection} />
        </div>
        {historyOpen && (
          <Modal title="Resume history" onClose={() => setHistoryOpen(false)} placement="right">
            <p className="mt-2 text-sm text-ink-muted">
              Every save is kept. Restoring saves the older version as a new one, so it can be
              undone too.
            </p>
            <div className="mt-4">
              <ResumeHistoryList showUndo />
            </div>
          </Modal>
        )}
      </BulletSkillsProvider>
    </EntryEditorProvider>
  );
}
