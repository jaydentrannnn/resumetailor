import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function Pagination({
  page,
  size,
  total,
  onPage,
  onSize,
}: {
  page: number;
  size: number;
  total: number;
  onPage: (page: number) => void;
  onSize: (size: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
      <span>
        {total
          ? `Showing ${page * size + 1}–${Math.min(total, (page + 1) * size)} of ${total}`
          : "0 results"}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <label>
          Rows{" "}
          <select
            aria-label="Rows per page"
            className="rounded-md border border-line bg-panel px-2"
            value={size}
            onChange={(e) => onSize(Number(e.target.value))}
          >
            {[25, 50, 100].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <button
          className="rounded-md border border-line bg-panel px-3 disabled:opacity-40"
          disabled={page === 0 || !total}
          onClick={() => onPage(page - 1)}
        >
          Previous
        </button>
        <label>
          Page{" "}
          <select
            aria-label="Page"
            className="rounded-md border border-line bg-panel px-2"
            value={Math.min(page, pages - 1)}
            onChange={(e) => onPage(Number(e.target.value))}
          >
            {Array.from({ length: pages }, (_, i) => (
              <option value={i} key={i}>
                {i + 1}
              </option>
            ))}
          </select>{" "}
          of {pages}
        </label>
        <button
          className="rounded-md border border-line bg-panel px-3 disabled:opacity-40"
          disabled={page >= pages - 1 || !total}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export type TableColumn<T> = {
  id: string;
  heading: string;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  className?: string;
};
export function DataTable<T>({
  rows,
  id,
  columns,
  selected,
  onSelected,
  sort,
  direction,
  onSort,
  empty,
  loading,
  error,
  selectable = () => true,
}: {
  rows: T[];
  id: (row: T) => string;
  columns: TableColumn<T>[];
  selected: Set<string>;
  onSelected: (next: Set<string>) => void;
  sort: string;
  direction: "asc" | "desc";
  onSort: (id: string) => void;
  empty: ReactNode;
  loading?: boolean;
  error?: string | null;
  selectable?: (row: T) => boolean;
}) {
  const checkbox = useRef<HTMLInputElement>(null);
  const mobileCheckbox = useRef<HTMLInputElement>(null);
  const eligible = rows.filter(selectable);
  const all = eligible.length > 0 && eligible.every((row) => selected.has(id(row)));
  const some = eligible.some((row) => selected.has(id(row)));
  useEffect(() => {
    if (checkbox.current) checkbox.current.indeterminate = some && !all;
    if (mobileCheckbox.current) mobileCheckbox.current.indeterminate = some && !all;
  }, [some, all]);
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-panel">
      {error && (
        <p role="alert" className="border-b border-line p-3 text-sm text-danger">
          {error}
        </p>
      )}
      <table className="hidden w-full table-fixed text-left text-sm md:table">
        <thead className="border-b border-line bg-bg text-ink-muted">
          <tr>
            <th className="w-10 px-2 py-2">
              <input
                ref={checkbox}
                type="checkbox"
                aria-label="Select this page"
                checked={all}
                disabled={!eligible.length}
                onChange={(e) => {
                  const next = new Set(selected);
                  eligible.forEach((row) =>
                    e.target.checked ? next.add(id(row)) : next.delete(id(row)),
                  );
                  onSelected(next);
                }}
              />
            </th>
            {columns.map((col) => (
              <th
                key={col.id}
                className={`px-2 py-2 font-medium ${col.className ?? ""}`}
                aria-sort={
                  col.sortable
                    ? sort === col.id
                      ? direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                    : undefined
                }
              >
                {col.sortable ? (
                  <button
                    type="button"
                    className="text-left hover:text-accent"
                    onClick={() => onSort(col.id)}
                  >
                    {col.heading}{" "}
                    <span aria-hidden="true">
                      {sort === col.id ? (direction === "asc" ? "↑" : "↓") : ""}
                    </span>
                  </button>
                ) : (
                  col.heading
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={id(row)}
              className="border-b border-line/60 last:border-0 hover:bg-accent-soft/20"
            >
              <td className="px-2 py-3 align-top">
                <input
                  type="checkbox"
                  aria-label={`Select ${id(row)}`}
                  checked={selected.has(id(row))}
                  disabled={!selectable(row)}
                  onChange={() => {
                    const next = new Set(selected);
                    if (next.has(id(row))) next.delete(id(row));
                    else next.add(id(row));
                    onSelected(next);
                  }}
                />
              </td>
              {columns.map((col) => (
                <td
                  key={col.id}
                  className={`min-w-0 px-2 py-3 align-top [overflow-wrap:anywhere] ${col.className ?? ""}`}
                >
                  {col.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="divide-y divide-line md:hidden">
        {!!rows.length && (
          <label className="flex items-center gap-2 p-3 text-xs text-ink-muted">
            <input
              ref={mobileCheckbox}
              type="checkbox"
              aria-label="Select this page"
              checked={all}
              disabled={!eligible.length}
              onChange={(e) => {
                const next = new Set(selected);
                eligible.forEach((row) =>
                  e.target.checked ? next.add(id(row)) : next.delete(id(row)),
                );
                onSelected(next);
              }}
            />{" "}
            Select this page
          </label>
        )}
        {rows.map((row) => (
          <article key={id(row)} className="space-y-2 p-3 text-sm">
            <label className="flex items-center gap-2 text-xs text-ink-muted">
              <input
                type="checkbox"
                aria-label={`Select ${id(row)}`}
                checked={selected.has(id(row))}
                disabled={!selectable(row)}
                onChange={() => {
                  const next = new Set(selected);
                  if (next.has(id(row))) next.delete(id(row));
                  else next.add(id(row));
                  onSelected(next);
                }}
              />{" "}
              Select
            </label>
            {columns.map((col) => (
              <div key={col.id} className="min-w-0 [overflow-wrap:anywhere]">
                <span className="mr-2 text-xs text-ink-muted">{col.heading}</span>
                {col.cell(row)}
              </div>
            ))}
          </article>
        ))}
      </div>
      {!rows.length && (
        <div className="p-8 text-center text-sm text-ink-muted">
          {loading ? "Loading applications…" : empty}
        </div>
      )}
    </div>
  );
}

// Links and buttons share one box: the global 36px min-height covers only <button>,
// so without `rt-control` a link item ("Tailored PDF") rendered shorter than "Skip".
// Size comes from the menu container, not the item: index.css's unlayered
// `button { font: inherit }` beats a `text-sm` utility on a <button>, so buttons
// only match links when both inherit one font size.
const menuItemClass =
  "rt-control flex w-full items-center rounded px-3 py-1.5 text-left hover:bg-accent-soft";
export type MenuItem = {
  label: string;
  action?: () => void;
  href?: string;
  disabled?: boolean;
  description?: string;
  danger?: boolean;
};
export function RowActionsMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  useEffect(() => {
    if (!open) return;
    const focus = window.requestAnimationFrame(() =>
      menu.current
        ?.querySelector<HTMLElement>("[role=menuitem]:not([aria-disabled=true])")
        ?.focus(),
    );
    const dismiss = (event: MouseEvent) => {
      if (
        !menu.current?.contains(event.target as Node) &&
        !button.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    const close = () => setOpen(false);
    document.addEventListener("pointerdown", dismiss);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.cancelAnimationFrame(focus);
      document.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);
  const buttons = items.filter((item) => !item.disabled);
  function keyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const active = Array.from(
      menu.current?.querySelectorAll<HTMLElement>("[role=menuitem]:not([aria-disabled=true])") ??
        [],
    );
    const index = active.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      setOpen(false);
      button.current?.focus();
    }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const next =
        e.key === "Home"
          ? 0
          : e.key === "End"
            ? active.length - 1
            : (index + (e.key === "ArrowDown" ? 1 : -1) + active.length) % active.length;
      active[next]?.focus();
    }
  }
  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        className="rt-row-action inline-flex w-7 shrink-0 items-center justify-center rounded-md border border-line bg-panel text-ink hover:border-line-hover"
        onClick={() => {
          setRect(button.current?.getBoundingClientRect() ?? null);
          setOpen(!open);
        }}
      >
        ⋯
      </button>
      {open &&
        rect &&
        createPortal(
          <div
            ref={menu}
            role="menu"
            onKeyDown={keyDown}
            className="fixed z-50 max-h-[70vh] w-52 overflow-auto rounded-md border border-line bg-panel p-1 text-sm shadow-xl"
            style={{
              left: Math.max(8, Math.min(rect.right - 208, window.innerWidth - 216)),
              top: rect.bottom + 220 > window.innerHeight ? undefined : rect.bottom + 4,
              bottom:
                rect.bottom + 220 > window.innerHeight
                  ? window.innerHeight - rect.top + 4
                  : undefined,
            }}
          >
            {items.map((item) =>
              item.href ? (
                <a
                  key={item.label}
                  role="menuitem"
                  href={item.href}
                  target="_blank"
                  rel="noreferrer"
                  aria-disabled={item.disabled}
                  tabIndex={item.disabled ? -1 : 0}
                  onClick={() => {
                    setOpen(false);
                    button.current?.focus();
                  }}
                  className={`${menuItemClass} text-ink`}
                >
                  {item.label}
                </a>
              ) : (
                <button
                  key={item.label}
                  type="button"
                  role="menuitem"
                  disabled={item.disabled}
                  aria-description={item.description}
                  className={`${menuItemClass} disabled:opacity-40 ${item.danger ? "text-danger" : "text-ink"}`}
                  onClick={() => {
                    setOpen(false);
                    button.current?.focus();
                    item.action?.();
                  }}
                >
                  {item.label}
                </button>
              ),
            )}
            {!buttons.length && <p className="p-2 text-xs text-ink-muted">No actions available</p>}
          </div>,
          document.body,
        )}
    </>
  );
}
