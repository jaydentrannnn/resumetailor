import { useState } from "react";
import { fetchSourceSections, inspectSource, type SourceConfig } from "../../api";
import { describe } from "../../lib/errors";
/**
 * The categories a README source offers, as checkboxes. The headings are read from the
 * README on demand, so a renamed category shows up instead of silently matching nothing.
 */
export function CategoryPicker({
  source,
  onChange,
  initialSections = null,
}: {
  source: SourceConfig;
  onChange: (next: SourceConfig) => void;
  /** Headings already read (the Add source dialog's inspect step); skips the fetch. */
  initialSections?: string[] | null;
}) {
  const [sections, setSections] = useState<string[] | null>(initialSections);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      // The inspect endpoint knows every README format, including per-company link tables.
      setSections(
        source.kind === "company_link_table"
          ? (await inspectSource(source.url)).sections
          : await fetchSourceSections(source.url),
      );
    } catch (reason) {
      setError(describe(reason).detail);
    } finally {
      setLoading(false);
    }
  }

  if (sections === null) {
    return (
      <div className="mt-1">
        <button
          type="button"
          className="rt-link text-xs disabled:opacity-50"
          onClick={load}
          disabled={loading}
        >
          {loading ? "Reading categories…" : "Choose categories"}
        </button>
        {error && (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        )}
      </div>
    );
  }
  const chosen = new Set(source.categories);
  const missing = source.categories.filter((c) => !sections.includes(c));
  return (
    <fieldset className="mt-2 space-y-1">
      <legend className="text-xs font-medium">Categories</legend>
      {sections.length === 0 && (
        <p className="text-xs text-ink-muted">
          This list has no category headings; every posting on it is searched.
        </p>
      )}
      {sections.map((name) => (
        <label key={name} className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={chosen.has(name)}
            onChange={(e) =>
              onChange({
                ...source,
                categories: e.target.checked
                  ? [...source.categories, name]
                  : source.categories.filter((c) => c !== name),
              })
            }
          />
          {name}
        </label>
      ))}
      {missing.length > 0 && (
        <p className="text-xs text-attn">
          Not in the list any more (finds nothing): {missing.join(" · ")}
        </p>
      )}
    </fieldset>
  );
}
