import { useState } from "react";
import { Card, Segmented, Switch } from "../../components/ui";
import {
  notificationsSupported,
  notifyPreference,
  setNotifyPreference,
} from "../../lib/applyNotify";
import { useToast } from "../../lib/toast";
import { type ThemePreference, useTheme } from "../../state/themeState";
import { SettingRow } from "./SettingRow";

const THEMES: { id: ThemePreference; label: string }[] = [
  { id: "system", label: "System" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];

/** Theme and system notifications: how the app looks and when it speaks up. */
export function AppearanceSection() {
  const { preference, setPreference } = useTheme();
  const toast = useToast();
  const [notify, setNotify] = useState(notifyPreference);

  async function changeNotify(on: boolean) {
    if (on && notificationsSupported() && Notification.permission === "default")
      await Notification.requestPermission();
    const granted = notificationsSupported() && Notification.permission === "granted";
    if (on && !granted)
      toast.error(
        "Notifications are blocked",
        "Allow notifications for this app in your system or browser settings, then try again.",
      );
    setNotify(on && granted);
    setNotifyPreference(on && granted);
  }

  return (
    <Card title="Appearance">
      <SettingRow label="Theme" description="System follows your computer's light or dark mode.">
        <Segmented
          label="Theme"
          items={THEMES}
          value={preference}
          onChange={(id) => setPreference(id as ThemePreference)}
        />
      </SettingRow>
      <SettingRow
        label="Notifications"
        description="When the window is in the background: a tailored resume is ready, an application needs you, or a run finishes."
      >
        {notificationsSupported() ? (
          <Switch label="Notifications" checked={notify} onChange={(on) => void changeNotify(on)} />
        ) : (
          <span className="text-xs text-ink-muted">Not available here</span>
        )}
      </SettingRow>
    </Card>
  );
}
