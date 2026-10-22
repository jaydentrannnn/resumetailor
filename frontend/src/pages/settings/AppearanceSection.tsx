import { useCallback, useEffect, useState } from "react";
import { fetchAppearance, fetchAutostart, saveAppearance, saveAutostart } from "../../api";
import { Button, Card, Segmented, SettingRow, Switch } from "../../components/ui";
import { RAIL_ITEMS, visibleRailItems, type RailLayout } from "../../components/shell/railItems";
import { buttonClass } from "../../lib/buttonClass";
import { useDesktop } from "../../lib/useDesktop";
import { useRunState } from "../../state/runState";
import { type ThemePreference, useTheme } from "../../state/themeState";
import { BannerCustomizeDialog } from "../apply/progress/BannerCustomizeDialog";

const THEME_ITEMS: { id: ThemePreference; label: string }[] = [
  { id: "system", label: "System" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];

/** Suggested accents (no red/orange: they collide with danger/attention). */
const ACCENT_SWATCHES = [
  { hex: null as string | null, label: "Default green" },
  { hex: "#2563eb", label: "Blue" },
  { hex: "#7c3aed", label: "Violet" },
  { hex: "#0d9488", label: "Teal" },
  { hex: "#0891b2", label: "Cyan" },
  { hex: "#4f46e5", label: "Indigo" },
];

const SCALES = [
  { value: 0.9, label: "90%" },
  { value: 1.0, label: "100%" },
  { value: 1.1, label: "110%" },
  { value: 1.25, label: "125%" },
  { value: 1.5, label: "150%" },
];

/**
 * Settings › Appearance: theme, accent, UI scale, opening page, sidebar, progress
 * banner and (desktop) start with computer.
 */
export function AppearanceSection() {
  const desktop = useDesktop();
  const { preference, setPreference, accent, setAccent } = useTheme();
  const { settings, setSettings } = useRunState();
  const [bannerOpen, setBannerOpen] = useState(false);
  const custom = !!accent && !ACCENT_SWATCHES.some((s) => s.hex === accent.toLowerCase());
  const [scale, setScale] = useState(1.0);
  const [autostart, setAutostart] = useState<{ enabled: boolean; supported: boolean } | null>(null);

  useEffect(() => {
    if (!desktop) return;
    fetchAppearance()
      .then((a) => setScale(a.scale))
      .catch(() => undefined);
    fetchAutostart()
      .then(setAutostart)
      .catch(() => setAutostart(null));
  }, [desktop]);

  const patchScale = useCallback((next: number) => {
    setScale(next);
    void saveAppearance({ scale: next }).catch(() => undefined);
  }, []);

  const layout: RailLayout = settings.rail_layout ?? { order: [], hidden: [] };
  const visible = visibleRailItems(layout);

  const setLayout = (next: RailLayout) => setSettings({ ...settings, rail_layout: next });

  const moveRail = (index: number, to: number) => {
    const order = visible.map((i) => i.to);
    const [item] = order.splice(index, 1);
    order.splice(to, 0, item);
    setLayout({ ...layout, order });
  };

  const toggleHidden = (to: string, show: boolean) => {
    const hidden = new Set(layout.hidden);
    if (show) hidden.delete(to);
    else {
      if (visible.length <= 1 && visible.some((i) => i.to === to)) return;
      hidden.add(to);
    }
    const order = layout.order.length
      ? layout.order
      : RAIL_ITEMS.filter((i) => !i.optional).map((i) => i.to);
    const nextOrder = show && !order.includes(to) ? [...order, to] : order;
    setLayout({ order: nextOrder, hidden: [...hidden] });
  };

  return (
    <div className="space-y-10">
      <Card title="Theme" description="Light, dark, or follow the computer.">
        <Segmented
          label="Theme"
          items={THEME_ITEMS}
          value={preference}
          onChange={(id) => setPreference(id as ThemePreference)}
        />
      </Card>

      <Card
        title="Accent color"
        description="Used for selected tabs, focus rings and the activity heatmap. Success stays green."
      >
        <div role="radiogroup" aria-label="Accent color" className="flex flex-wrap gap-2">
          {ACCENT_SWATCHES.map((swatch) => {
            const selected =
              swatch.hex === null ? accent === null : accent?.toLowerCase() === swatch.hex;
            return (
              <button
                key={swatch.label}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setAccent(swatch.hex)}
                className={`flex items-center gap-2 rounded-sm border px-2.5 py-1.5 text-sm ${
                  selected ? "border-ink text-ink" : "border-line text-ink-2"
                }`}
              >
                <span
                  aria-hidden
                  className="size-3.5 rounded-[3px]"
                  style={{
                    background: swatch.hex ?? "var(--color-accent)",
                  }}
                />
                {swatch.label}
              </button>
            );
          })}
          <label
            className={`relative flex cursor-pointer items-center gap-2 rounded-sm border px-2.5 py-1.5 text-sm focus-within:outline focus-within:outline-2 focus-within:outline-[var(--color-accent)] ${
              custom ? "border-ink text-ink" : "border-line text-ink-2"
            }`}
          >
            {/* The native picker's own swatch is a bar that matches nothing else here, so it
                stays invisible over the whole button (its dialog anchors to the button). */}
            <input
              type="color"
              aria-label="Custom accent"
              className="absolute inset-0 size-full cursor-pointer opacity-0"
              value={accent ?? "#1f6b4a"}
              onChange={(e) => setAccent(e.target.value)}
            />
            <span
              aria-hidden
              className="size-3.5 rounded-[3px]"
              style={{
                background: custom
                  ? accent!
                  : "conic-gradient(#2563eb, #7c3aed, #0d9488, #0891b2, #4f46e5, #2563eb)",
              }}
            />
            Custom
          </label>
        </div>
      </Card>

      {desktop && (
        <Card title="UI scale" description="Makes everything larger or smaller in the desktop app.">
          <SettingRow label="Scale" layout="action">
            <Segmented
              label="UI scale"
              items={SCALES.map((s) => ({ id: String(s.value), label: s.label }))}
              value={String(scale)}
              onChange={(id) => patchScale(Number(id))}
            />
          </SettingRow>
        </Card>
      )}

      <Card title="Opening page" description="Which page opens when the app starts.">
        <SettingRow label="Start on" layout="action">
          <select
            aria-label="Opening page"
            className="field w-auto"
            value={settings.start_page ?? "/"}
            onChange={(e) => setSettings({ ...settings, start_page: e.target.value })}
          >
            {visible.map((item) => (
              <option key={item.to} value={item.to}>
                {item.label}
              </option>
            ))}
          </select>
        </SettingRow>
      </Card>

      <Card title="Sidebar" description="Show, hide and reorder pages. Settings always stays.">
        {desktop && (
          <SettingRow
            label="Show shortcut hints"
            layout="action"
            description="Ctrl 1–n and Ctrl , beside the pages. The shortcuts work either way."
          >
            <Switch
              className="ml-auto"
              label="Show shortcut hints"
              checked={settings.show_shortcut_hints !== false}
              onChange={(on) => setSettings({ ...settings, show_shortcut_hints: on })}
            />
          </SettingRow>
        )}
        <ul className="mt-2 space-y-2">
          {RAIL_ITEMS.map((item) => {
            const shown = visible.some((v) => v.to === item.to);
            const index = visible.findIndex((v) => v.to === item.to);
            return (
              <li
                key={item.to}
                className="flex flex-wrap items-center gap-2 border-t border-line py-2 first:border-0"
              >
                <Switch
                  label={`Show ${item.label}`}
                  checked={shown}
                  onChange={(on) => toggleHidden(item.to, on)}
                />
                <span className="min-w-0 flex-1 text-sm font-medium">{item.label}</span>
                {shown && (
                  <span className="flex gap-1">
                    <button
                      type="button"
                      className={buttonClass("ghost", "sm", "min-w-9 px-2")}
                      aria-label={`Move ${item.label} up`}
                      disabled={index <= 0}
                      onClick={() => moveRail(index, index - 1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className={buttonClass("ghost", "sm", "min-w-9 px-2")}
                      aria-label={`Move ${item.label} down`}
                      disabled={index >= visible.length - 1}
                      onClick={() => moveRail(index, index + 1)}
                    >
                      ↓
                    </button>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
        {!visible.some((v) => v.to === "/applications") && (
          <p className="mt-2 text-xs text-attn">
            Apply is hidden, so its &quot;needs you&quot; count will not show in the side bar.
          </p>
        )}
        <div className="mt-3">
          <Button variant="plain" size="sm" onClick={() => setLayout({ order: [], hidden: [] })}>
            Reset sidebar
          </Button>
        </div>
      </Card>

      <Card
        title="Progress banner"
        description="The banner over the Apply list. Options are saved for this profile."
      >
        <SettingRow label="Customize" layout="action">
          <Button className="ml-auto" onClick={() => setBannerOpen(true)}>
            Customize progress banner
          </Button>
        </SettingRow>
      </Card>

      {desktop && autostart?.supported && (
        <Card
          title="Start with computer"
          description="Opens in the tray so the nightly Apply run can still fire. The app must be installed as the desktop app."
        >
          <SettingRow label="Launch at login" layout="action">
            <Switch
              className="ml-auto"
              label="Launch at login"
              checked={autostart.enabled}
              onChange={(on) => {
                setAutostart({ ...autostart, enabled: on });
                void saveAutostart(on)
                  .then(setAutostart)
                  .catch(() => setAutostart({ ...autostart, enabled: !on }));
              }}
            />
          </SettingRow>
        </Card>
      )}

      {bannerOpen && <BannerCustomizeDialog onClose={() => setBannerOpen(false)} />}
    </div>
  );
}
