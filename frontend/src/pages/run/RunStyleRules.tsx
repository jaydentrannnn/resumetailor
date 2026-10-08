import type { AppConfig, JobSettings } from "../../api";
import { StylePromptField } from "../../components/StylePromptField";

type Setter = <K extends keyof JobSettings>(key: K, value: JobSettings[K]) => void;

type StyleKey = "rewrite_style" | "expand_style" | "cover_style";

/** The three per-stage writing style blocks, each over its locked core rules. */
export function RunStyleRules({
  config,
  settings,
  set,
}: {
  config: AppConfig | null;
  settings: JobSettings;
  set: Setter;
}) {
  /** Store an override only when it differs from the shipped default. */
  function setStyle(key: StyleKey, text: string | null, defaultText: string | undefined) {
    if (text === null) {
      set(key, null);
      return;
    }
    const trimmed = text.trim();
    set(key, !trimmed || trimmed === defaultText?.trim() ? null : text);
  }

  const blocks: { key: StyleKey; label: string; help: string; def?: string; core?: string }[] = [
    {
      key: "rewrite_style",
      label: "Resume bullet style",
      help: "Voice and emphasis for this profile. Length limits are enforced; field guidance prioritizes accurate verbs over forced variety.",
      def: config?.rewrite_style_default,
      core: config?.rewrite_core_rules,
    },
    {
      key: "expand_style",
      label: "Application-form expansion style",
      help: "Voice rules for the longer experience descriptions pasted into application forms.",
      def: config?.expand_style_default,
      core: config?.expand_core_rules,
    },
    {
      key: "cover_style",
      label: "Cover letter style",
      help: "Voice and structure rules for the cover letter body paragraphs.",
      def: config?.cover_style_default,
      core: config?.cover_core_rules,
    },
  ];

  return (
    <details className="border-y border-line py-3">
      <summary className="cursor-pointer text-sm font-medium text-ink">Writing style rules</summary>
      <div className="mt-3 space-y-4">
        {blocks.map((block) => (
          <StylePromptField
            key={block.key}
            label={block.label}
            help={block.help}
            value={settings[block.key]}
            defaultText={block.def ?? ""}
            lockedCoreRules={block.core ?? ""}
            onChange={(text) => setStyle(block.key, text, block.def)}
          />
        ))}
      </div>
    </details>
  );
}
