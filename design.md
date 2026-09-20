# Design — ResumeTailor

A locked design system for this app. Every page redesign reads this file before
emitting code. Do not regenerate per page — extend or amend this file when the
system needs to grow.

## Scope note — this is an app, not a marketing site

ResumeTailor's frontend has no landing page, no marketing funnel, no content site —
four functional routes (Tailor / Master resume / Template / Vocabulary), all forms
and panels over a job-configuration pipeline. Hallmark's 21 named macrostructures
(Bento Grid, Marquee Hero, Workbench, …) are landing-page shapes; none of them
describe a settings screen honestly. Rather than force-fit one, this system defines
**app-page structural rules directly** (containment, density, rhythm) instead of a
hero macrostructure. `macrostructure: n/a — functional app shell` is the correct,
stated value for every page here — not a gap.

## Genre
**editorial**, intentionally against type. The obvious route for a job-tooling
utility is modern-minimal (Stripe/Linear grotesk-sans). This app already committed
to Fraunces + a forest-green accent — a considered pairing, not a template default —
and nothing in the audit suggested the palette itself was the problem. Kept.

## Tone
**utilitarian**, applied to *structure* (density, containment, rhythm) rather than
to typography. The serif stays; the box-in-a-box nesting and undifferentiated
panel rhythm go.

## Theme
Closest catalog match: **Studio** (light paper · high-contrast-serif · chromatic
green accent). Values below are this app's own measured tokens, not Studio's
shipped defaults — kept because they already work, converted to OKLCH for the
system record.

Light:
- `--color-paper`        oklch(95.5% 0.011 89.7)
- `--color-panel`        oklch(100% 0 0)
- `--color-ink`          oklch(25.5% 0.031 260.4)
- `--color-ink-muted`    oklch(50.5% 0.033 261.4)
- `--color-line`         oklch(86.5% 0.020 87.5)
- `--color-accent`       oklch(48.1% 0.091 170.1)
- `--color-accent-soft`  oklch(93.5% 0.029 168.8)
- `--color-warn`         oklch(47.0% 0.143 37.3)
- `--color-danger`       oklch(45.5% 0.171 13.7)
- `--color-focus`        = `--color-accent`

Dark (`[data-theme="dark"]`):
- `--color-paper`        oklch(22.5% 0.005 248.0)
- `--color-panel`        oklch(26.7% 0.005 248.0)
- `--color-ink`          oklch(92.0% 0.013 86.8)
- `--color-ink-muted`    oklch(71.4% 0.018 84.6)
- `--color-line`         oklch(37.3% 0.009 248.1)
- `--color-accent`       oklch(71.1% 0.122 169.3)
- `--color-accent-soft`  oklch(33.0% 0.046 170.5)
- `--color-warn`         oklch(75.8% 0.159 55.9)
- `--color-danger`       oklch(71.9% 0.169 13.4)

Diversification axes (for any *future* page added to this app — not for redesigning
the four that exist, which must all match this file): paper-band **light**,
display-style **high-contrast-serif**, accent-hue **chromatic-other (green)**.

## Typography
- Display: Fraunces (variable, opsz 9–144), weight 500/700, roman only
- Body: IBM Plex Sans, weight 400/500/600
- Mono: IBM Plex Mono, weight 400 — new role, added for style-prompt textareas,
  ids, and code-like fields that were previously falling back to the browser
  default monospace stack with no token behind them
- Micro-label: 11px (0.6875rem), uppercase, tracking-wide — replaces five
  different arbitrary sizes (`text-[0.65rem]`, `text-[10px]`, `text-[11px]`) that
  had drifted into the app with no shared token

## Spacing
Tailwind's default 4-pt scale, used directly (`p-3`/`p-4`/`p-5`/`gap-2`/…) — no
custom `--space-*` scale needed since Tailwind's own numeric scale already is one
and every existing call site already uses it. What changes is *variance*: not
every panel gets `p-5` any more — see § Density below.

## Motion
- `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)`
- `--ease-in: cubic-bezier(0.7, 0, 0.84, 0)`
- `--ease-in-out: cubic-bezier(0.65, 0, 0.35, 1)`
- `--dur-short: 150ms` (colour/border/opacity state changes)
- `--dur-base: 220ms` (width/transform transitions, the progress bar)
- Duration scale 1.0× (Studio default) — this app was already restrained; no
  animation removed, just given named durations/easings instead of the browser
  default `ease` and bare `transition` it was riding on
- Reduced-motion fallback already correct (`index.css`, kept as-is)

## Microinteractions stance
- Silent success everywhere already (no celebratory toasts existed) — kept
- **Reversed:** entry/bullet/section removal in the Master-resume editor is now
  optimistic-delete + Undo, not a confirmation modal. Nothing there is persisted
  until the explicit Save button — a modal was asking the user to confirm an edit
  to their own unsaved draft. The vocabulary-strip flow (removing an in-use tag,
  which rewrites *other* bullets) keeps its confirmation — that one is real.
- Danger-toned confirm dialogs focus Cancel, not the destructive action, on open
- Hover delay / focus delay split not applicable — no tooltips with a hover-only
  delay exist in this app (all `title=` attributes are supplementary, not the
  only channel, except where noted as a remaining minor)

## CTA voice
- Primary action: solid `--color-accent` fill, `--color-on-accent` text, no
  border, `rounded-lg`
- Secondary action: `--color-line` hairline border, `--color-ink-muted` text,
  hover moves to `--color-accent` border+text — never opacity-fade (opacity-fade
  on a solid fill reads as disabled, not hovered; kept for outline buttons where
  the fade is the only signal, replaced with a fill-darken on solid danger buttons)
- Destructive action: solid `--color-danger` fill or `--color-danger` outline,
  hover darkens the fill rather than fading opacity

## Priority — the primary input leads, settings follow
A page's *first* screenful is its primary action, not the knobs that configure
it. The Tailor page had this backwards: Settings + What-to-include occupied
row 1 — sized to the taller of the two (What-to-include, measured at 1,628px)
— with Job description in row 2 below it, so the one thing every run needs
started at y=1,848px. Row order is now Job description + Progress first,
Settings + What-to-include second, matching source order so mobile gets the
same priority the desktop grid does. Apply this rule to any future panel
arrangement on a page with one dominant action: ask "what did the user come
here to do," put that first, put configuration after.

## Chips
`ChipListField` pills are **neutral by default** (`border-line` + `bg-paper`,
`text-ink`) — a committed token (a tag, a skill, a suppressed alias), not a
selection state. Accent shows only on the remove button's hover, the one
moment a chip is genuinely "active." This was accent-filled originally; at
the volumes this component renders (a full tag vocabulary, every bullet's own
tags — 600+ chips on one Master-resume page) the accent stopped being a
signal and became the page's background texture. If a future chip usage
genuinely needs a selected/unselected distinction (a filter, not a token
list), that's the one case allowed to reach for `--color-accent-soft` again —
name it explicitly when you do.

## Embedded PDF chrome
Every PDF `<iframe>` appends `#toolbar=0&navpanes=0` to its `src` — Chrome's
own PDF toolbar + thumbnail rail is the viewer's UI, not this app's, and at
full chrome it was the darkest, most alien element on an otherwise cream
page. "Open in new tab" links (next to every embed) still point at the bare
URL, so a full viewer with real download/print controls is one click away.
Applies to every current and future inline PDF preview in this app.

## Disclosure for oversized settings panels
A settings panel that would otherwise dominate a page above the content it
configures (Master resume's ~150-tag vocabulary list, previously 712px above
Contact and every resume section) collapses into a native `<details>`,
closed by default, with a count in the summary line. Reuse the pattern
already established by `ReportCard`'s "Coverage gaps (N)" — `list-none`
summary, a manual `▾` marker rotated via `group-open:rotate-180`. This is
the standing answer to "a settings block is bigger than the content" —
collapse it, don't shrink its content or move it off-page unless it
genuinely belongs on a different route.

## Density — the one real structural change
Every panel in this app used the same `rounded-xl border border-line bg-panel p-5
shadow-sm` at every nesting level — section card, entry card, bullet card, three
deep in the Master-resume editor. One containment layer survives per view:

- **Section-level panels** (`RunPage`'s Settings/Include/Progress tiles,
  `EditorPage`'s section cards, `VocabularyPage`'s three numbered sections) keep
  the bordered panel treatment — this is the one real container per screen.
- **Repeated rows inside a panel** (education/experience/project entries, skill
  groups, bullets) drop the nested border+tint box and become `divide-y
  divide-line` rows with padding only. A bullet inside an entry gets a left rule
  (`border-l-2 border-line/60 pl-4`), not its own box — hierarchy by indentation
  and a rule, not by nesting containers.
- Panels are no longer uniformly `p-5` — the primary content panel on each route
  keeps `p-5`; secondary/metadata panels (Progress-tile idle state, Template
  page's metadata grid cells) tighten to `p-4` and, where they're informational
  rather than actionable, drop the shadow.

## Nav
**N1b (canonical three-section)** — wordmark left, theme/profile utility cluster
+ primary nav right. This is what the app already had in spirit; the fix is
making it survive 320px (`flex-wrap` on the whole right-hand cluster, shorter
link labels) rather than swapping to a different archetype. No footer archetype
— this is a functional app, not a page with a marketing close; the last thing on
each screen is its own last functional panel (Run History on the Tailor tab), and
inventing an `Ft#` footer under it would be exactly the AI-footer tell the audit
already cleared this app of.

## Per-page allowances
- No marketing pages exist. No enrichment (Tier-A/B/C) anywhere — every page is
  function-first, per the app-page rule.
- Content pages: n/a (none exist).

## What pages MUST share
- Fraunces display + IBM Plex Sans body + IBM Plex Mono for code-like fields
- The forest-green accent and its ≤5%-of-viewport placement discipline
- The one-containment-layer rule (§ Density)
- The CTA voice (fill/outline/danger treatments above)
- Neutral-by-default chips (§ Chips)
- `#toolbar=0&navpanes=0` on every embedded PDF (§ Embedded PDF chrome)
- Primary-input-before-settings ordering on any page with one dominant action
  (§ Priority)
- `:focus-visible` as the *only* focus treatment — no per-component
  `outline-none` overrides, ever (this was the single most-repeated bug in the
  prior pass: two components had quietly reintroduced `outline-none` after the
  global rule was written specifically to remove it)

## What pages MAY differ on
- Panel density (§ Density) per what the panel actually is
- Whether a panel shows a shadow (actionable panels do; informational ones don't)

## Exports

### tokens.css
```css
:root {
  --color-paper:       oklch(95.5% 0.011 89.7);
  --color-panel:        oklch(100% 0 0);
  --color-ink:          oklch(25.5% 0.031 260.4);
  --color-ink-muted:    oklch(50.5% 0.033 261.4);
  --color-line:         oklch(86.5% 0.020 87.5);
  --color-accent:       oklch(48.1% 0.091 170.1);
  --color-accent-soft:  oklch(93.5% 0.029 168.8);
  --color-on-accent:    oklch(100% 0 0);
  --color-warn:         oklch(47.0% 0.143 37.3);
  --color-warn-soft:    oklch(95.4% 0.037 75.2);
  --color-danger:       oklch(45.5% 0.171 13.7);
  --color-danger-soft:  oklch(94.1% 0.030 12.6);
  --color-focus:        oklch(48.1% 0.091 170.1);
  --color-doc-preview:  #ffffff; /* literal — represents an actual white document page, not a UI surface */

  --font-display: "Fraunces", Georgia, serif;
  --font-sans:    "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  --font-mono:    "IBM Plex Mono", ui-monospace, "SFMono-Regular", monospace;

  --text-micro: 0.6875rem;

  --ease-out:    cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in:     cubic-bezier(0.7, 0, 0.84, 0);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --dur-short: 150ms;
  --dur-base:  220ms;
}

:root[data-theme="dark"] {
  --color-paper:       oklch(22.5% 0.005 248.0);
  --color-panel:       oklch(26.7% 0.005 248.0);
  --color-ink:         oklch(92.0% 0.013 86.8);
  --color-ink-muted:   oklch(71.4% 0.018 84.6);
  --color-line:        oklch(37.3% 0.009 248.1);
  --color-accent:      oklch(71.1% 0.122 169.3);
  --color-accent-soft: oklch(33.0% 0.046 170.5);
  --color-on-accent:   oklch(15% 0.03 170);
  --color-warn:        oklch(75.8% 0.159 55.9);
  --color-danger:      oklch(71.9% 0.169 13.4);
  --color-focus:       oklch(71.1% 0.122 169.3);
}
```

### Tailwind v4 `@theme`
See `frontend/src/index.css` — the live source of truth. This app uses Tailwind
v4's `@theme` block directly rather than a separate `tokens.css`; the block above
is the portable mirror for reuse outside this project.

### DTCG `tokens.json` / shadcn variables
Not generated — no consumer for either format exists in this codebase today. Add
on request per `export-formats.md`.
