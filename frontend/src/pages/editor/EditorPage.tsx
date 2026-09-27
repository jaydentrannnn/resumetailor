import { useEffect, useRef, useState } from "react";
import { Modal } from "../../components/Modal";
import { ResumeHistoryList } from "../../components/ResumeHistoryList";
import { ImportResumePanel } from "../../components/ImportResumePanel";
import { useEditorState } from "../../state/editorState";
import { AddSectionPanel, SectionShell } from "./SectionShell";
import { TagVocabularyPanel } from "./TagVocabularyPanel";
import { TextField } from "./TextField";
import {
  type MasterResume,
  type Section,
  type SectionKind,
  SECTION_KIND_LABELS,
  addToVocabulary,
  blankSection,
  collectBulletIds,
  collectEntryIds,
  collectSectionIds,
  looksLikeHttpUrl,
  moveItem,
  nextSectionId,
  removeAt,
} from "../../lib/resumeEdit";

type UndoToast = { id: number; message: string; snapshot: MasterResume };

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
  /** Inside Profile, whose single save bar replaces this page's Save button and pill. */
  embedded?: boolean;
}) {
  const {
    resume,
    setResume,
    config,
    errors,
    message,
    busy,
    dirty,
    validate: onValidate,
    save: onSave,
  } = useEditorState();

  const tagVocab = new Set([...(resume?.tag_vocabulary ?? []), ...(config?.tag_vocabulary ?? [])]);
  const vocabList = [...tagVocab].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));

  const takenBulletIds = resume ? collectBulletIds(resume) : new Set<string>();
  const takenEntryIds = resume ? collectEntryIds(resume) : new Set<string>();

  const [toasts, setToasts] = useState<UndoToast[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const nextToastId = useRef(0);
  const timersRef = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  // Mirrors `resume` between renders so a removal handler several components deep
  // (which only has its own section, not the full document) can still snapshot the
  // whole resume for Undo without every list component threading `resume` itself.
  const resumeRef = useRef(resume);
  useEffect(() => {
    resumeRef.current = resume;
  }, [resume]);

  useEffect(
    () => () => {
      for (const timer of timersRef.current.values()) clearTimeout(timer);
    },
    [],
  );

  function dismissToast(id: number) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }

  /**
   * Register an already-applied removal for Undo. Nothing in this editor persists
   * until the explicit Save button, so a confirmation modal on every row delete was
   * asking the user to confirm an edit to their own draft — this replaces that with
   * optimistic delete + a 6s Undo, restoring the exact pre-removal resume snapshot.
   * Callers invoke this *before* applying their own removal, in the same synchronous
   * click handler — `resumeRef` only updates via the effect above, which runs after
   * this handler returns, so it still holds the pre-removal value at capture time.
   */
  function pushUndo(message: string) {
    if (!resumeRef.current) return;
    const snapshot = resumeRef.current;
    const id = nextToastId.current++;
    setToasts((prev) => [...prev, { id, message, snapshot }]);
    timersRef.current.set(
      id,
      setTimeout(() => dismissToast(id), 6000),
    );
  }

  function undoToast(id: number) {
    const toast = toasts.find((t) => t.id === id);
    if (toast) setResume(toast.snapshot);
    dismissToast(id);
  }

  if (!resume) {
    return (
      <p className="text-sm text-ink-muted">
        {errors.length ? errors.join("; ") : "Loading master resume…"}
      </p>
    );
  }

  function ensureVocab(token: string) {
    /** Promote a newly typed tag into the stored vocabulary list. */
    setResume((prev) => ({
      ...prev,
      tag_vocabulary: addToVocabulary(prev.tag_vocabulary ?? [], token),
    }));
  }

  function updateSection(index: number, next: Section) {
    setResume((prev) => {
      const sections = [...prev.sections];
      sections[index] = next;
      return { ...prev, sections };
    });
  }

  function addSection(kind: SectionKind, title: string) {
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

  return (
    <>
      <div className="space-y-6">
        {/* bg-panel (not bg-paper/85) so the sticky bar reads as a toolbar sitting
          above the page, not a translucent cream-on-cream band that only shows
          up as a faint seam. shadow-sm carries the same "this is elevated"
          signal the rest of the app's panels use. Rounded and inset like the other
          cards: it lives inside the Profile page now, not full-bleed under the nav. */}
        <div className="sticky top-0 z-20 rounded-xl border border-line bg-panel px-5 py-3 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="font-display text-2xl font-semibold">Master resume</h1>
              <p className="text-sm text-ink-muted">
                Every fact a tailored resume can use lives here. Tags double as the fabrication
                guard&apos;s whitelist.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {dirty && !embedded && (
                <span className="rounded-full bg-warn-soft px-2.5 py-1 text-xs font-medium text-warn">
                  Unsaved changes
                </span>
              )}
              <button
                type="button"
                onClick={() => setHistoryOpen(true)}
                className="rounded-md border border-line px-3 py-2 text-sm font-medium hover:border-accent"
              >
                History
              </button>
              <button
                type="button"
                onClick={onValidate}
                disabled={busy}
                className="rounded-md border border-line px-3 py-2 text-sm font-medium hover:border-accent disabled:opacity-50"
              >
                Validate
              </button>
              {!embedded && (
                <button
                  type="button"
                  onClick={onSave}
                  disabled={busy}
                  className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-on-accent disabled:opacity-50"
                >
                  Save
                </button>
              )}
            </div>
          </div>
          {message && (
            <p
              role="status"
              aria-live="polite"
              className="mt-2 max-h-32 overflow-y-auto rounded-md bg-accent-soft px-3 py-2 text-sm text-accent"
            >
              {message}
            </p>
          )}
          {errors.length > 0 && (
            <ul
              role="alert"
              className="mt-2 max-h-32 overflow-y-auto rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
            >
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </div>

        <details className="rounded-lg border border-line bg-panel p-4">
          <summary className="cursor-pointer text-sm font-medium text-accent">
            Import resume content
          </summary>
          <div className="mt-3">
            <ImportResumePanel />
          </div>
        </details>

        <TagVocabularyPanel resume={resume} onChange={setResume} />

        {showContact && (
          <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <h2 className="font-display text-lg font-semibold">Contact</h2>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <TextField
                label="Name"
                value={resume.contact.name}
                onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, name: v } })}
              />
              <TextField
                label="Email"
                value={resume.contact.email}
                onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, email: v } })}
              />
              <TextField
                label="Phone"
                value={resume.contact.phone ?? ""}
                onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, phone: v } })}
              />
              <TextField
                label="Location"
                value={resume.contact.location ?? ""}
                onChange={(v) =>
                  setResume({ ...resume, contact: { ...resume.contact, location: v } })
                }
              />
              <TextField
                label="LinkedIn URL"
                value={resume.contact.linkedin ?? ""}
                onChange={(v) =>
                  setResume({ ...resume, contact: { ...resume.contact, linkedin: v } })
                }
              />
              <TextField
                label="GitHub URL"
                value={resume.contact.github ?? ""}
                onChange={(v) =>
                  setResume({ ...resume, contact: { ...resume.contact, github: v } })
                }
              />
            </div>
            {(resume.contact.linkedin ?? "").trim() &&
              !looksLikeHttpUrl(resume.contact.linkedin ?? "") && (
                <p className="mt-2 text-xs text-warn">
                  LinkedIn URL should start with http:// or https://.
                </p>
              )}
            {(resume.contact.github ?? "").trim() &&
              !looksLikeHttpUrl(resume.contact.github ?? "") && (
                <p className="mt-2 text-xs text-warn">
                  GitHub URL should start with http:// or https://.
                </p>
              )}
          </section>
        )}

        <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:items-start lg:gap-5">
          <label className="mb-3 block text-sm lg:hidden">
            Jump to section
            <select
              className="field mt-1"
              defaultValue=""
              onChange={(event) =>
                document
                  .getElementById(`resume-section-${event.target.value}`)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              <option value="" disabled>
                Choose a section
              </option>
              {resume.sections.map((section) => (
                <option key={section.id} value={section.id}>
                  {section.title || SECTION_KIND_LABELS[section.kind]}
                </option>
              ))}
            </select>
          </label>
          <nav aria-label="Resume sections" className="sticky top-4 hidden space-y-1 lg:block">
            {resume.sections.map((section) => (
              <a
                key={section.id}
                href={`#resume-section-${section.id}`}
                className="block rounded-md px-2 py-1.5 text-sm text-ink-muted hover:bg-accent-soft hover:text-accent"
              >
                {section.title || SECTION_KIND_LABELS[section.kind]}
              </a>
            ))}
          </nav>
          <div className="space-y-5">
            {resume.sections.map((section, i) => (
              <div
                key={section.id}
                id={`resume-section-${section.id}`}
                data-resume-section
                className="scroll-mt-4"
              >
                <SectionShell
                  key={section.id}
                  section={section}
                  index={i}
                  total={resume.sections.length}
                  vocabList={vocabList}
                  takenBulletIds={takenBulletIds}
                  takenEntryIds={takenEntryIds}
                  onEnsureVocab={ensureVocab}
                  pushUndo={pushUndo}
                  onRemove={(idx) => {
                    const removedTitle = resume.sections[idx]?.title || "section";
                    pushUndo(`Removed “${removedTitle}”`);
                    setResume((prev) => ({ ...prev, sections: removeAt(prev.sections, idx) }));
                  }}
                  onMove={(from, to) =>
                    setResume((prev) => ({ ...prev, sections: moveItem(prev.sections, from, to) }))
                  }
                  onChange={(next) => updateSection(i, next)}
                />
              </div>
            ))}
          </div>
        </div>

        <p className="text-xs text-ink-muted">
          Reordering sections changes bullet scoring order — the next Tailor run will re-score once
          (one extra LLM call) before using the new order.
        </p>

        <AddSectionPanel onAdd={addSection} />
      </div>
      {historyOpen && (
        <Modal title="Resume history" onClose={() => setHistoryOpen(false)} placement="right">
          <p className="mt-2 text-sm text-ink-muted">
            Every save is kept. Restoring saves the older version as a new one, so it can be undone
            too.
          </p>
          <div className="mt-4">
            <ResumeHistoryList showUndo />
          </div>
        </Modal>
      )}
      {toasts.length > 0 && (
        <div className="fixed inset-x-0 bottom-4 z-30 flex flex-col items-center gap-2 px-4 sm:items-end sm:pr-6">
          {toasts.map((t) => (
            <div
              key={t.id}
              role="status"
              className="flex items-center gap-3 rounded-lg border border-line bg-panel px-4 py-2.5 text-sm text-ink shadow-lg"
            >
              <span>{t.message}</span>
              <button
                type="button"
                onClick={() => undoToast(t.id)}
                className="font-semibold text-accent underline-offset-2 hover:underline"
              >
                Undo
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
