import { useState } from "react";
import { Tile } from "../ui";
import {
  GalleryActions,
  GalleryCard,
  GalleryRow,
  TemplateThumb,
  selectButtonClass,
} from "./TemplateGallery";
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
export function StarterTemplatesPanel({
  embedded = false,
}: {
  /** Inside the onboarding step tile: a hairline section instead of its own tile. */
  embedded?: boolean;
} = {}) {
  const Title = embedded ? "h3" : "h2";
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
    <Tile
      id="starter-templates"
      aria-labelledby="starter-templates-title"
      embedded={embedded}
      className={embedded ? "border-t border-line pt-4" : ""}
    >
      <Title id="starter-templates-title" className="rt-tile-title">
        Starter templates
      </Title>
      <p className="mt-1 text-sm text-ink-muted">
        Clean single-column layouts that work with every feature. Pick one if your own file uses
        text boxes or a sidebar, or if you imported a PDF. Your resume content stays the same.
      </p>
      <GalleryRow>
        {defaults.map((t) => (
          <GalleryCard key={t.name} active={t.is_active}>
            <TemplateThumb
              src={defaultTemplateThumbUrl(t.name)}
              alt={`Sample page in the ${t.label} template`}
            />
            <div className="flex flex-1 flex-col gap-2 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-ink">{t.label}</span>
                {!t.is_active && t.library_id ? (
                  <span className="text-xs text-ink-muted">Saved</span>
                ) : null}
              </div>
              <p className="text-xs text-ink-muted">{t.description}</p>
              <GalleryActions>
                <button
                  type="button"
                  disabled={busy || t.is_active}
                  onClick={() => void use(t.name, t.education_first)}
                  className={selectButtonClass(t.is_active)}
                >
                  {t.is_active ? "In use" : `Use ${t.label}`}
                </button>
              </GalleryActions>
            </div>
          </GalleryCard>
        ))}
      </GalleryRow>
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
