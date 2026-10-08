import { Tile } from "../ui";
import { buttonClass } from "../../lib/buttonClass";
import { useState } from "react";
import { defaultTemplateThumbUrl, fetchMasterResume, saveMasterResume } from "../../api";
import { educationFirst, needsEducationFirst } from "../../lib/sectionOrder";
import { useConfirm } from "../../state/confirmState";
import { useEditorState } from "../../state/editorState";
import { useTemplateState } from "../../state/templateState";
import type { MasterResume } from "../../lib/resumeEdit";

/**
 * Built-in starter templates: a clean layout for students whose own file can't be a
 * template (text boxes, sidebars) or who don't have a .docx at all.
 */
export function StarterTemplatesPanel() {
  const { defaults, installDefault, libraryBusy, uploading } = useTemplateState();
  const { dirty, syncFromDisk } = useEditorState();
  const { confirm } = useConfirm();
  const [notice, setNotice] = useState<string | null>(null);
  const busy = libraryBusy || uploading;

  async function offerEducationFirst() {
    const resume = (await fetchMasterResume()) as { sections?: { kind?: unknown }[] };
    const sections = resume.sections ?? [];
    if (!needsEducationFirst(sections)) return;
    if (dirty) {
      setNotice(
        "This template lists Education first. Save your resume edits, then move Education to the top in the editor.",
      );
      return;
    }
    const ok = await confirm({
      title: "Put Education first?",
      message:
        "This template lists Education at the top, as finance and consulting recruiters expect. Move your Education section to the top of your resume? You can change the order later in the editor.",
      confirmLabel: "Move Education up",
    });
    if (!ok) return;
    const next = { ...resume, sections: educationFirst(sections) };
    await saveMasterResume(next);
    syncFromDisk(next as unknown as MasterResume, "Education moved to the top.");
    setNotice("Education is now the first section of your resume.");
  }

  async function use(name: string, reorder: boolean) {
    setNotice(null);
    const ok = await installDefault(name);
    if (ok && reorder) {
      try {
        await offerEducationFirst();
      } catch (err) {
        setNotice(err instanceof Error ? err.message : String(err));
      }
    }
  }

  if (defaults.length === 0) return null;
  return (
    <Tile id="starter-templates" aria-labelledby="starter-templates-title">
      <h2 id="starter-templates-title" className="rt-tile-title">
        Starter templates
      </h2>
      <p className="mt-1 text-sm text-ink-muted">
        Clean single-column layouts that work with every feature. Pick one if your own file uses
        text boxes or a sidebar, or if you imported a PDF. Your resume content stays the same.
      </p>
      <ul className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(180px,200px))]">
        {defaults.map((t) => (
          <li
            key={t.name}
            className={`flex flex-col overflow-hidden rounded-sm border bg-field text-sm ${
              t.is_active ? "border-selected-line" : "border-line"
            }`}
          >
            <Thumbnail name={t.name} label={t.label} />
            <div className="flex flex-1 flex-col gap-2 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-ink">{t.label}</span>
                {t.is_active ? (
                  <span className="rounded-sm border border-selected-line bg-selected px-1.5 py-0.5 text-xs font-medium text-on-selected">
                    In use
                  </span>
                ) : t.library_id ? (
                  <span className="text-xs text-ink-muted">Saved</span>
                ) : null}
              </div>
              <p className="text-xs text-ink-muted">{t.description}</p>
              <div className="mt-auto">
                <button
                  type="button"
                  disabled={busy || t.is_active}
                  onClick={() => void use(t.name, t.education_first)}
                  className={
                    t.is_active
                      ? "rounded-sm border border-selected-line bg-selected px-3 py-1.5 text-xs font-medium text-on-selected"
                      : buttonClass("secondary", "sm")
                  }
                >
                  {t.is_active ? "In use" : `Use ${t.label}`}
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {busy ? (
        <p className="mt-3 text-sm text-ink-muted" role="status">
          Setting up the template…
        </p>
      ) : null}
      {notice ? (
        <p className="mt-3 rounded-sm bg-accent-soft px-3 py-2 text-sm text-ink" role="status">
          {notice}
        </p>
      ) : null}
    </Tile>
  );
}

/** First page of the design with its sample content; a plain card without a PDF engine. */
function Thumbnail({ name, label }: { name: string; label: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="flex h-56 items-start justify-center overflow-hidden bg-doc-preview">
      {failed ? (
        <span className="m-auto px-4 text-center text-xs text-ink-muted">
          Preview unavailable (needs Word or LibreOffice)
        </span>
      ) : (
        <img
          src={defaultTemplateThumbUrl(name)}
          alt={`Sample page in the ${label} template`}
          loading="lazy"
          className="h-full w-full object-contain object-top"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}
