import { type KeyboardEvent } from "react";

type TabItem = { id: string; label: string };

export function Tabs({
  items,
  value,
  onChange,
  label,
}: {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  label: string;
}) {
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = Math.max(
      0,
      items.findIndex((item) => item.id === value),
    );
    const next =
      event.key === "ArrowRight"
        ? items[(current + 1) % items.length]
        : event.key === "ArrowLeft"
          ? items[(current + items.length - 1) % items.length]
          : event.key === "Home"
            ? items[0]
            : event.key === "End"
              ? items[items.length - 1]
              : null;
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    (event.currentTarget.querySelector(`[data-tab="${next.id}"]`) as HTMLElement | null)?.focus();
  }
  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex flex-wrap gap-2 border-b border-line pb-2"
      onKeyDown={onKeyDown}
    >
      {items.map((item) => (
        <button
          type="button"
          key={item.id}
          role="tab"
          data-tab={item.id}
          aria-selected={value === item.id}
          tabIndex={value === item.id ? 0 : -1}
          className={`rounded-md px-3 py-2 text-sm ${value === item.id ? "bg-accent text-on-accent" : "text-ink-muted hover:bg-accent-soft"}`}
          onClick={() => onChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
