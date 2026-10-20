import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { type Command, matchCommands } from "../lib/commands";
import { shortcutFor } from "../lib/shortcuts";
import { useCommandList } from "../state/commandState";
import { Kbd } from "./ui/Tile";

/**
 * Ctrl/Cmd+K: a list of every page and every action the open page offers, filtered as
 * you type. Enter runs the highlighted one; Escape closes and gives focus back.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const list = useCommandList();
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (shortcutFor(e) !== "commands") return;
      e.preventDefault();
      setOpen((was) => !was);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  if (!open) return null;
  return <PaletteDialog list={list} onClose={() => setOpen(false)} />;
}

function PaletteDialog({ list, onClose }: { list: () => Command[]; onClose: () => void }) {
  const [commands, setCommands] = useState(list);
  // Opening moved focus out of the page, so a buffered field has just committed: list
  // again once the page has re-rendered with it.
  useEffect(() => {
    const timer = window.setTimeout(() => setCommands(list()), 0);
    return () => window.clearTimeout(timer);
  }, [list]);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const shown = matchCommands(commands, query);
  const current = shown[Math.min(active, shown.length - 1)];

  // Read while rendering: by the time effects run, autoFocus has moved focus already.
  const [previous] = useState(() => document.activeElement as HTMLElement | null);
  useEffect(() => () => previous?.focus?.(), [previous]);
  useEffect(() => {
    listRef.current
      ?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView?.({ block: "nearest" });
  }, [current]);

  function run(command: Command) {
    onClose();
    // After the dialog has closed and handed focus back, so a command can move it. The
    // command is looked up again then: the one listed may hold a stale closure (a Save
    // from before a field committed) or no longer be allowed.
    window.setTimeout(() => {
      const fresh = list().find((item) => item.id === command.id);
      if (fresh && !fresh.disabled) fresh.run();
    }, 0);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const move = { ArrowDown: 1, ArrowUp: -1 }[e.key];
    if (move && shown.length) {
      e.preventDefault();
      setActive(
        (index) => (Math.min(index, shown.length - 1) + move + shown.length) % shown.length,
      );
    } else if (e.key === "Enter" && current) {
      e.preventDefault();
      run(current);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/30 px-4 pt-[12vh]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Commands"
        className="mx-auto max-w-xl overflow-hidden rounded-sm border border-line bg-chrome shadow-lg"
      >
        <input
          autoFocus
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={current ? `${listId}-${current.id}` : undefined}
          aria-label="Find a page or an action"
          placeholder="Find a page or an action…"
          className="w-full border-b border-line bg-transparent px-4 py-3 text-sm text-ink outline-none placeholder:text-ink-muted"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
        <ul ref={listRef} id={listId} role="listbox" className="max-h-[50vh] overflow-y-auto py-1">
          {shown.map((command, i) => (
            <li
              key={command.id}
              id={`${listId}-${command.id}`}
              role="option"
              aria-selected={command === current}
              onMouseMove={() => setActive(i)}
              onClick={() => run(command)}
              className={`flex min-h-10 cursor-pointer items-center gap-3 px-4 py-1.5 text-sm ${command === current ? "bg-selected-row text-ink" : "text-ink"}`}
            >
              <span className="min-w-0 flex-1 truncate">{command.title}</span>
              <span className="shrink-0 text-xs text-ink-muted">{command.group}</span>
              {command.shortcut && (
                <span className="flex shrink-0 gap-1">
                  {command.shortcut.map((key) => (
                    <Kbd key={key}>{key}</Kbd>
                  ))}
                </span>
              )}
            </li>
          ))}
          {!shown.length && (
            <li className="px-4 py-3 text-sm text-ink-muted">Nothing matches “{query}”.</li>
          )}
        </ul>
      </div>
    </div>,
    document.body,
  );
}
