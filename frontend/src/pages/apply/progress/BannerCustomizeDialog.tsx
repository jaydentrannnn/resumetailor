import { Modal } from "../../../components/Modal";
import { Button } from "../../../components/ui";
import { useRunState } from "../../../state/runState";
import { useWorkspaceState } from "../../../state/workspaceState";
import { ProgressBanner } from "./ProgressBanner";
import { ProgressBannerSetting } from "./ProgressBannerSetting";

/**
 * Live preview of the Apply progress banner with its options below. The panel is
 * banner-width so the preview matches the Apply page; options sit in columns under it.
 * Changes autosave for this profile through run settings.
 */
export function BannerCustomizeDialog({ onClose }: { onClose: () => void }) {
  const { settings, setSettings } = useRunState();
  const { activeId } = useWorkspaceState();
  const apply = settings.apply;
  const patch = (fields: Partial<typeof apply>) =>
    setSettings({ ...settings, apply: { ...apply, ...fields } });

  return (
    <Modal title="Progress banner (this profile)" onClose={onClose} size="xl">
      <div className="mt-4 space-y-6">
        <div className="rounded-sm border border-line bg-panel p-3 sm:p-4">
          <p className="rt-eyebrow mb-2">Preview</p>
          <ProgressBanner
            apply={apply}
            workspaceId={activeId ?? ""}
            revision={0}
            onTab={() => undefined}
            onSettings={() => undefined}
            preview
          />
        </div>
        <ProgressBannerSetting apply={apply} patch={patch} columns />
        <div className="flex justify-end">
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    </Modal>
  );
}
