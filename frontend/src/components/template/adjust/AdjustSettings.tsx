import { useState } from "react";
import type { CurrentLayout, TemplateFonts } from "../../../api";
import {
  bulletsSummary,
  emphasisChanged,
  marginsSummary,
  printedSeparatorRows,
  separatorsChanged,
} from "../../../lib/templateAdjust";
import { AdjustSection } from "./AdjustSection";
import { FieldEmphasisTable } from "./FieldEmphasisTable";
import { BulletFields, SeparatorFields } from "./MarksSections";
import { FontSection, MarginFields } from "./PageFontSections";

type SectionId = "margins" | "bullets" | "separators" | "emphasis";

const changed = (n: number, total: string) => (n ? `${n} changed` : total);

/**
 * Quick adjustments' settings: Font always open, then the larger groups collapsed, one
 * open at a time. Each collapsed header says what the group is set to.
 */
export function AdjustSettings({
  current,
  draft,
  onChange,
  fonts,
  tableLayout,
}: {
  current: CurrentLayout;
  draft: CurrentLayout;
  onChange: (next: CurrentLayout) => void;
  fonts: TemplateFonts;
  tableLayout: boolean;
}) {
  const [open, setOpen] = useState<SectionId | null>(null);
  const section = (id: SectionId) => ({
    open: open === id,
    onToggle: () => setOpen((now) => (now === id ? null : id)),
  });
  const separators = printedSeparatorRows(draft).length;
  const emphasisRows = draft.fields.length + (draft.links ? 1 : 0);

  return (
    <div>
      <FontSection draft={draft} onChange={onChange} fonts={fonts} />
      <AdjustSection
        title="Margins"
        summary={marginsSummary(draft.margins)}
        {...section("margins")}
      >
        <MarginFields draft={draft} onChange={onChange} tableLayout={tableLayout} />
      </AdjustSection>
      <AdjustSection
        title="Bullet styles"
        summary={bulletsSummary(draft.bullets)}
        {...section("bullets")}
      >
        <BulletFields draft={draft} onChange={onChange} />
      </AdjustSection>
      {separators > 0 && (
        <AdjustSection
          title="Separators"
          summary={changed(separatorsChanged(current, draft), `${separators} kinds`)}
          {...section("separators")}
        >
          <SeparatorFields draft={draft} onChange={onChange} />
        </AdjustSection>
      )}
      <AdjustSection
        title="Field emphasis"
        summary={changed(emphasisChanged(current, draft), `${emphasisRows} rows`)}
        {...section("emphasis")}
      >
        <FieldEmphasisTable
          fields={draft.fields}
          onChange={(fields) => onChange({ ...draft, fields })}
          links={draft.links}
          onLinksChange={(links) => onChange({ ...draft, links })}
        />
      </AdjustSection>
    </div>
  );
}
