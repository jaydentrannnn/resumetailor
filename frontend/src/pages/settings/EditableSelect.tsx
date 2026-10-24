import { useState } from "react";

type Option = { value: string; label: string; group?: string };

/**
 * Native settings dropdown with an explicit escape hatch for new IDs. With
 * `customBeside`, the typed ID is its own grid cell beside the dropdown, not under it.
 */
export function EditableSelect({
  label,
  value,
  options,
  placeholder,
  customLabel,
  customBeside = false,
  onChange,
}: {
  label: string;
  value: string;
  options: Option[];
  placeholder: string;
  customLabel: string;
  customBeside?: boolean;
  onChange: (value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const custom = editing || (!!value && !options.some((option) => option.value === value));
  const groups = [...new Set(options.map((option) => option.group ?? ""))];
  const entries = (group: string) =>
    options
      .filter((option) => (option.group ?? "") === group)
      .map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ));
  const field = custom && (
    <label className={`block min-w-0 text-sm font-medium ${customBeside ? "" : "mt-2"}`}>
      {customLabel}
      <input
        className="field mt-1 font-mono"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
  const select = (
    <label className="block min-w-0 text-sm font-medium">
      {label}
      <select
        className="field mt-1"
        value={custom ? "__custom__" : value}
        onChange={(event) => {
          const next = event.target.value;
          setEditing(next === "__custom__");
          if (next !== "__custom__") onChange(next);
        }}
      >
        <option value="">{placeholder}</option>
        {groups.map((group) =>
          group ? (
            <optgroup key={group} label={group}>
              {entries(group)}
            </optgroup>
          ) : (
            entries(group)
          ),
        )}
        <option value="__custom__">{customLabel}…</option>
      </select>
    </label>
  );
  return customBeside ? (
    <>
      {select}
      {field}
    </>
  ) : (
    <div className="min-w-0">
      {select}
      {field}
    </div>
  );
}
