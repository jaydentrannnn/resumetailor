# ResumeTailor interface guide

Visual target: `docs/design/reference.html` (serve `docs/design` with
`python -m http.server` and open it; the theme switch is at the top, the "Other screens"
bar shows sub-screens). This file is the written contract behind it. The tokens live in
`frontend/src/index.css`, the components in `frontend/src/components/ui/`.

## Principles

- **Deep black, bright white, one racing-green accent, serif titles, 4px corners, calm
  grey tiles.** The page is white (`#0a0a0a` in dark); content sits on soft grey tiles set
  off by a hairline border.
- **Flat.** No gradients, no blur, no card shadows. Only overlays (menus, popovers,
  toasts, modals) carry one shadow, the same everywhere.
- **Spacing before boxes.** Inside a tile separate things with space or one hairline
  (`TileSection`). Never nest boxes. Label/value data is separated by spacing, not divider
  cells (`DataList`).
- **Status is never colour alone.** Every status has a text label and its own mark shape.
- **Green means selected, progress, tick or focus — never a button fill.**

Don'ts: `rounded-xl/2xl/full` (except the Spinner and Meter tracks), `shadow-sm/md`,
`backdrop-blur`, `bg-white`, new colour tokens, hand-built `bg-accent text-on-accent`
buttons, the retired `warn`/`info` tokens, nested bordered boxes, dashed borders on empty
states.

## Tokens

Defined in the `@theme` block of `index.css`; dark values under `:root[data-theme="dark"]`.
Use the Tailwind classes (`bg-panel`, `text-ink-muted`, `border-line`), never raw hex.

| Token | Light | Dark | Use |
|---|---|---|---|
| `paper` | `#ffffff` | `#0a0a0a` | page |
| `chrome` | `#ffffff` | `#0a0a0a` | header, overlays, sticky bars |
| `panel` | `#f7f7f6` | `#151515` | tile surface |
| `sunken` | `#efefed` | `#1d1d1d` | segment track, hover, skeleton, meter track |
| `field` | `#ffffff` | `#0f0f0f` | input background |
| `line` / `line-hover` | `#e2e2df` / `#c8c8c4` | `#2a2a2a` / `#3d3d3d` | hairline / control border |
| `ink` / `ink-2` / `ink-muted` | `#0b0b0b` / `#3a3a38` / `#6b6b68` | `#f5f5f4` / `#d4d4d2` / `#8f8f8c` | text |
| `primary` / `on-primary` | `#0b0b0b` / `#fff` | `#ffffff` / `#0b0b0b` | primary button |
| `accent` | `#1f6b4a` | `#6fbf98` | progress, ticks, focus, active nav |
| `accent-soft` | 6% accent | 12% accent | quiet green wash |
| `selected` / `on-selected` / `selected-line` | `#1f6b4a` / `#fff` / `#1f6b4a` | 12% mint / `#6fbf98` / `#6fbf98` | selected segment, tab, filter |
| `selected-row` | 9% accent | 12% mint | selected table row wash |
| `success` | `#1f6b4a` | `#6fae90` | done mark (chips only) |
| `attn` / `attn-soft` | `#b0390a` / 10% | `#e0965c` / 8% | "needs you" |
| `danger` / `danger-soft` | `#c42020` / 10% | `#d17875` / 8% | failed, destructive |
| `scrim` | 40% black | 60% black | modal backdrop |
| `doc-preview` | `#ffffff` | `#ffffff` | an actual white PDF page; not a UI surface |

The old `warn`, `warn-soft`, `warning`, `info`, `info-soft` and `bg` tokens were deleted at
integration; use `attn`/`attn-soft` (or `ink-muted` for a plain note) and `paper`.

Radius: `--radius-sm` … `--radius-4xl` are all 4px, so `rounded-md` and `rounded-lg` are
4px too; prefer `rounded-sm`. `rounded-xs` is 2px for tiny marks. Shadow: `shadow-2xs` …
`shadow-md` are none; `shadow-lg/xl/2xl` are the single overlay shadow (light: soft drop +
hairline ring; dark: 1px ring only).

## Type

Fraunces Variable (titles, big figures), Geist Variable (body and UI), Geist Mono Variable
(data), all self-hosted via `@fontsource-variable/*` imported in `main.tsx` — nothing is
fetched from a CDN, so the desktop app works offline.

| Role | Class | Spec |
|---|---|---|
| Page title | `rt-title` | Fraunces 350, 32→50px fluid, −0.015em |
| Big figure | `rt-figure` | Fraunces 350, 40→56px, tabular numbers |
| Eyebrow / table head / `dt` | `rt-eyebrow` | Geist Mono 11px caps, 0.08em, muted |
| Tile title | `rt-tile-title` | 15px / 600 |
| Inline text link | `rt-link` | `text-ink`, underline, 2px offset, accent on hover |
| Body, table text | — | 14px (13px dense) |
| Supporting text | — | 12px, `text-ink-muted` |
| Times, counts, IDs, model names | `font-mono` | Geist Mono, tabular numbers |

Controls are at least 36px tall (44px on coarse pointers). Header pills are exactly
`rt-header-pill rt-control`: 36px/44px at 12px/16px/600 — a Playwright test pins this.
Never add an unlayered `font: inherit` reset; it beats Tailwind text utilities.

**Links.** An inline text link (in a sentence, an empty state, a toast, "Connect", "Open
in new tab") is `rt-link`: ink with an underline, accent on hover. Never green at rest and
never a colour class beside it — the utility owns the colour. Size and weight utilities
(`text-xs`, `font-medium`) are fine. Quiet secondary actions that are deliberately muted
(`text-ink-muted … hover:underline`) and destructive ones keep their own tone; a link that
should look like a button uses `buttonClass`.

## Selected state

One accent, two renderings, exposed as tokens so pages only write classes:

- **Light:** solid green fill, white text — `bg-selected text-on-selected`.
- **Dark:** mint text, 1px mint border, ~12% mint wash — the same classes plus the inset
  ring `shadow-[inset_0_0_0_1px_var(--color-selected-line)]` (in light the ring is the
  same colour as the fill, so it is invisible).
- **Table rows / record cards (both themes):** wash plus a 2px inset accent bar on the
  left, via `data-selected="true"` on the `<tr>` (`DataTable` sets it) or on an element
  with class `rt-record`.

## Status taxonomy

`Tone` (`lib/tone.ts`): each tone has a hue, a mark shape and always a word.

| Tone | Mark | Hue | Means |
|---|---|---|---|
| `done` | check | success green | submitted, fits, saved |
| `ready` | dot | success green | ready to act on now (an application ready to fill) |
| `attention` | ring | orange | needs you — urgent, waiting on the user |
| `failed` | diamond | red | something broke |
| `live` | spinner | outline | working now |
| `neutral` | dot | ink | unknown, early pipeline |
| `muted` | dash | outline, muted | closed, rejected, ghosted |

`ready` is a green dot, not a check: actionable, not yet done. Attention is orange (urgent)
and failed is red; there is no blue status. Application
statuses map through `lib/applicationStatus.ts` (`applicationStatusTone`).

## Anatomy

- **PageHeader:** mono `eyebrow`, serif `rt-title` h1, one-line lede, `actions` on the
  right, optional `back` link above. Every page starts with it, then tiles.
- **Tile:** grey surface, 1px `line` border, 4px corners, 20–24px padding. Optional
  eyebrow, `rt-tile-title` h2, `meta`, `actions`. Sub-sections use `TileSection` (one
  hairline).
- **DataList:** wrapping `<dl>`, `gap-x-8`; `dt` is an eyebrow, `dd` 15px/500. No dividers.
- **Stat:** serif figure over a 12px caption.

## Buttons, tables, selection

- **Buttons** (`Button` / `buttonClass`): primary is ink — black in light, **white in
  dark**; secondary is the same ink fill (a `field`-coloured secondary vanished into its
  tile in both themes, so it was dropped 2026-10-08); outline is the quiet one — ink border
  and ink text on `sunken` — for low-weight actions (pagination, Save beside an input,
  Copy, Export, drawer links); danger is a red outline (also the destructive confirm);
  ghost is muted text. On/off settings that apply at once use `Switch` (the Job sources
  track), not a checkbox; checkboxes stay for picking items from a list. Header utilities
  (Pause automation, the settings menu) are borderless text like the nav; the menu marks
  the active profile and theme with the accent bar/underline, not a box. Every button and button-styled link has the same 36px
  floor (44px on touch, via `rt-control` in `buttonClass`); `sm` only changes text and
  padding. Use `md` for page and tile actions and `sm` only in dense rows; table row
  actions use `rt-row-action` (28px). Green is never a fill. Use one primary per tile or
  dialog; positive actions (Save changes, Fill) are primary.
- **Settings rows** (`pages/settings/SettingRow`): `layout="split"` (label | control),
  `"stacked"` (control under the label, full width) or `"action"` (text left, buttons
  right-aligned) — buttons in one tile line up on the right.
- **Long text in rows** (`TruncatedText`): table cells and notice rows show one line;
  when it is cut off the line is a button that opens the full text in a floating box at
  the click point (outside click, Escape or Close dismiss it). Never let descriptions wrap
  a table row.
- **Tables** (`DataTable`, `Pagination`, `RowActionsMenu`): eyebrow headers over a
  stronger hairline, hairlines between rows, hover `bg-sunken`, selected rows as above,
  mono pager. Below `md` the same rows render as record cards.
- **SelectionBar:** `role=toolbar`, mono count, bulk actions, Clear. Only while rows are
  selected.
- **Overlays** (`Modal`, menus, `InlineHelp`, `Toast`): `bg-chrome`, 4px, the overlay
  shadow, `bg-scrim` backdrop without blur. Toasts carry a status chip for the kind.

## Accessibility

- Contrast: all light text/hue values are ≥ 5.3:1; dark attention/danger/success are
  ≥ 5.8/5.8/7.0 on `#151515`; white primary on black is 18.2:1. Axe must pass in both
  themes.
- Focus: one 2px accent ring (`:focus-visible`), never removed.
- Marks are `aria-hidden` and paired with text; progress uses `role=progressbar` with a
  name; tabs/radiogroups keep full ARIA and arrow-key behaviour.
- Reduced motion is honoured globally in `index.css`.
- Layouts must not scroll horizontally at 390px; header wraps instead.

## Primitives

All exported from `components/ui` (`import { … } from "../components/ui"`).

| Primitive | Props | Use it when |
|---|---|---|
| `Page` | `width?: "standard" \| "wide"`, `className` | The shell of every page: `standard` is one centred 6xl column, `wide` is a full-width dashboard. |
| `PageHeader` | `title`, `eyebrow?`, `description?`, `back?`, `actions?` | The first thing on every page. |
| `Tile` (alias `Card`) | `title?`, `eyebrow?`, `meta?`, `description?`, `actions?`, `as?`, `padding?: "md" \| "sm" \| "none"`, `embedded?`, `className`, `id`/`aria-*`/`data-*` | Any grouped content. Default element is `<section>`; pass `as="aside"` etc. `embedded` renders the same heading and content with no box (no border, fill or padding) and the title as an h3 — for a tile's content shown inside another tile. |
| `ResultFrame` | `embedded?`, `title?`, `description?`, `actions?`, `className` | The frame of a result card (report, documents, skills, experience, bullet review): a `Tile` standalone, unboxed with an h3 when `embedded` inside another tile. |
| `TileSection` | `title?`, `actions?`, `className` | A second group inside a tile, separated by one hairline instead of a nested box. |
| `Button` | `variant?: "primary" \| "secondary" \| "outline" \| "danger" \| "ghost"`, `size?: "sm" \| "md" \| "lg"`, `loading?`, + button attrs | Every button. `buttonClass(variant, size, extra)` styles links as buttons. |
| `StatusChip` | `tone: Tone`, `children` (label), `className`, `mark?` (default `true`) | A status pill: mark + word. `mark={false}` only where the label carries its own typed glyph (the e2e-anchored "● Connected" on Job sources). |
| `StatusMark` | `tone: Tone` | Just the mark, inside your own labelled element (the label must still be text). |
| `Segmented` | `items: {id,label,count?,disabled?}[]`, `value`, `onChange(id)`, `label`, `className` | One-of-N choice that is not a content switch (theme, view mode, filter). Renders a radiogroup. |
| `Tabs` | `items: {id,label,count?}[]`, `value`, `onChange(id)`, `label`, `variant?: "underline" \| "segmented"`, `orientation?: "horizontal" \| "vertical"` | Switching panels. `underline` for page sections, `segmented` for a view inside a tile, `vertical` for a side rail. A horizontal strip that overflows (390px) scrolls itself so the selected tab stays visible; the page never scrolls. |
| `Meter` | `value?` (0–100), `label`, `valueText?`, `indeterminate?`, `tone?: "accent" \| "danger" \| "ink"`, `className` | Progress. Always give it a `label`. |
| `DataList` | `items: {label,value}[]`, `mono?`, `className` | Summaries of label/value pairs (options, report facts). |
| `Stat` | `value`, `label`, `className` | Big serif figures (page count, match score). |
| `SelectionBar` | `count`, `noun?`, `onClear`, `clearLabel?`, `label?` (toolbar aria-label, default "Selection actions"), `children` (actions) | The toolbar above a table while rows are selected; render only when `count > 0`. |
| `Stepper` | `steps: {id,label,meta?}[]`, `current`, `failed?`, `onSelect?`, `label?`, `orientation?`, `divided?` | Wizards and run progress; square marks, optional mono meta per step. `divided` (vertical only) puts hairlines between rows and right-aligns `meta` — the Tailor run stages. |
| `Modal` | `title`, `onClose`, `wide?`, `placement?: "center" \| "right"` | Dialogs and the Apply settings drawer. |
| `InlineHelp` | `label`, `children` | A "?" explanation next to a label. |
| `TruncatedText` | `text`, `className`, `label` | One-line text; click-to-expand floating box when cut off. |
| `EmptyState` | `title`, `icon?`, `children?`, `action?` | A list/page with nothing yet. |
| `Skeleton` | `className` | Loading placeholder blocks. |
| `Kbd` | `children` | A keyboard key. |
| `Field` / `Toggle` | `label`, `help?`, … | Label + control pairs; inputs use the `.field` class. |
| `ToastProvider` + `useToast()` | `success/error/info(title, detail?, action?)` | Transient messages (`lib/toast.ts`). |
| `DataTable`, `Pagination`, `RowActionsMenu` | see `components/TableControls.tsx`; `DataTable` also takes `bare?`, `selectable?: boolean \| (row) => boolean`, `className` | Tables with selection, paging and row menus. `bare` drops the table's own border, corners and panel fill when it sits directly on a `Tile`; `selectable={false}` removes the checkbox column and the mobile "Select" labels for read-only lists. |
| `useConfirm()` | `confirm({title,message,tone?,…})`, `choice({…})` | Promise-based dialogs; never `window.confirm`. |

Shared sections with an `embedded` prop (the onboarding steps pass it; Settings and
Template keep the tiled default): `ModelsSection`, `TargetFieldSection`,
`TemplateImportWizard`, `StarterTemplatesPanel` (and `ImportResumePanel`). Embedded they
render as hairline-separated sections inside the step tile instead of tiles of their own.

If a page needs something these do not cover, ask for a primitive rather than patching a
shared file or hand-building the look.

## Parity (extension, splash, icons)

The extension popup/options, the content-script chip, the desktop splash and the icons
follow the same palette, 4px corners, black/white primary and single green accent, but
cannot share this stylesheet: the extension self-hosts its own fonts (`extension/fonts`),
the chip uses system fonts (it lives in a host page's shadow DOM) and the splash uses a
system serif. Keep their hex values in step with the token table above.

## Logo

The mark is the "RT" page (`docs/design/logo/resumetailor-mark-{black,white}.svg`, the
full-size source art). The SPA header uses cropped, downscaled copies
(`frontend/src/assets/logo-mark-{black,white}.svg`, 154×192, ~7 KB) at `h-5` (20px tall)
before the serif wordmark; `.rt-logo-light` / `.rt-logo-dark` in `index.css` show the copy
that matches `data-theme`. Regenerate the header copies from the source art (crop to the
mask's alpha bounds, scale to 192px tall) rather than editing them by hand.
