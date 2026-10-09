import { saveModelQueue } from "../../api";
import { Button, Card } from "../../components/ui";
import { describe } from "../../lib/errors";
import { settingsFor } from "../../lib/speedPresets";
import { useToast } from "../../lib/toast";
import { useConfirm } from "../../state/confirmState";
import { resetSettings } from "../../state/runDefaults";
import { useRunState } from "../../state/runState";
import { SettingRow } from "./SettingRow";

/** The one place that puts tailoring options and advanced AI tuning back to defaults. */
export function ResetSettingsCard() {
  const { config, settings, setSettings } = useRunState();
  const { confirm } = useConfirm();
  const toast = useToast();

  async function reset() {
    const ok = await confirm({
      title: "Reset settings to defaults?",
      message:
        "Tailoring options (pages, cover letter, bullets, writing style rules, what to include) and the advanced AI settings go back to their defaults. Your AI models, API keys, Apply settings, resume and files are kept.",
      confirmLabel: "Reset",
      tone: "danger",
    });
    if (!ok) return;
    setSettings(resetSettings(settings, config));
    try {
      await saveModelQueue(settingsFor("balanced"));
      toast.success("Settings reset to defaults");
    } catch (err) {
      toast.error("Could not reset the speed setting", describe(err).detail);
    }
  }

  return (
    <Card title="Reset settings">
      <SettingRow
        label="Defaults"
        layout="action"
        description="Tailoring options and advanced AI settings go back to their defaults. Models, keys, Apply settings and your data are kept."
      >
        <Button onClick={() => void reset()}>Reset to defaults…</Button>
      </SettingRow>
    </Card>
  );
}
