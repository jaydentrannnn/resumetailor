import { useEffect, useId, useMemo, useState, type KeyboardEvent } from "react";
import type { TemplateFonts } from "../../../api";
import { fontGroups, isInstalled } from "../../../lib/fontSearch";

/**
 * A searchable font box (ARIA combobox): typing filters the installed fonts, arrows move,
 * Enter picks, Esc closes. Each name shows in its own typeface. Fonts come from the
 * machine that makes the PDF; one not installed there is still listed, with a note.
 */
export function FontPicker({
  value,
  fonts,
  onChange,
  labelId,
}: {
  value: string;
  fonts: TemplateFonts;
  onChange: (font: string) => void;
  labelId: string;
}) {
  const [query, setQuery] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const listId = useId();
  const open = query !== null;
  const families = fonts.families.length ? fonts.families : [value];
  const groups = useMemo(
    () => fontGroups(families, fonts.common, query ?? ""),
    [families, fonts.common, query],
  );
  const flat = groups.flatMap((g) => g.fonts);
  const optionId = (i: number) => `${listId}-${i}`;

  useEffect(() => {
    if (open)
      document.getElementById(`${listId}-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, open, listId]);

  const choose = (font: string) => {
    onChange(font);
    setQuery(null);
  };

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return setQuery("");
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => Math.min(Math.max(i + step, 0), Math.max(flat.length - 1, 0)));
    } else if (e.key === "Enter" && open) {
      e.preventDefault();
      if (flat[active]) choose(flat[active]);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      setQuery(null);
    }
  }

  let index = -1;
  return (
    <div className="relative">
      <input
        role="combobox"
        aria-labelledby={labelId}
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && flat.length ? optionId(active) : undefined}
        className="field w-full"
        style={{ fontFamily: open ? undefined : `"${value}"` }}
        value={open ? query : value}
        placeholder={value}
        onFocus={() => {
          setQuery("");
          setActive(Math.max(flat.indexOf(value), 0));
        }}
        onBlur={() => setQuery(null)}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
        }}
        onKeyDown={onKeyDown}
      />
      {open && (
        <div
          id={listId}
          role="listbox"
          aria-labelledby={labelId}
          className="absolute inset-x-0 top-full z-20 mt-1 max-h-72 overflow-y-auto rounded-md border border-line bg-chrome py-1 shadow-lg"
        >
          {flat.length === 0 && (
            <p className="px-3 py-2 text-xs text-ink-muted">No font matches.</p>
          )}
          {groups.map((group) => (
            <div key={group.label} role="group" aria-label={group.label}>
              <p className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                {group.label}
              </p>
              {group.fonts.map((font) => {
                index += 1;
                const i = index;
                return (
                  <div
                    key={font}
                    id={optionId(i)}
                    role="option"
                    aria-selected={font === value}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => choose(font)}
                    onMouseEnter={() => setActive(i)}
                    className={`cursor-pointer truncate px-3 py-1.5 text-sm ${i === active ? "bg-sunken" : ""} ${font === value ? "font-semibold" : ""}`}
                    style={{ fontFamily: `"${font}"` }}
                  >
                    {font}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
      {fonts.families.length > 0 && !isInstalled(value, fonts.families) && (
        <p className="mt-1 text-xs text-attn">
          Not installed here, so the PDF will use a substitute.
        </p>
      )}
    </div>
  );
}
