# ResumeTailor interface guide

The five top-level views are Tailor, Apply, Profile, Template, and Vocabulary. Profile switching, profile management, and the theme live in one settings menu at the right of the header, not as separate header controls. They use the same warm neutral surfaces, teal actions, and IBM Plex Sans type. The charcoal dark theme keeps its original low-glare background. Use IBM Plex Mono only for technical values, IDs, and code. Do not introduce page-specific palettes or decorative gradients.

| Role | Light | Dark |
|---|---|---|
| Page | `#F7F6F2` | `#1A1C1E` |
| Panel | `#FFFFFF` | `#242628` |
| Text | `#202725` | `#E8E4DB` |
| Secondary text | `#626A65` | `#A8A296` |
| Border | `#DEDCD4` | `#3D4145` |
| Accent | `#087F73` | `#3DBA95` |
| Accent background | `#E2F0EB` | `#1A3D32` |
| On accent | `#FFFFFF` | `#0A1A14` |

Keep semantic warning and danger colors separate from the accent. Always label statuses in text. Preserve the shared focus ring and reduced-motion rule. Page headings are 28px/600, section headings 18px/600, body and table text 14px, and supporting text 12px. Controls are at least 36px tall, or 44px for coarse pointers. Controls have 6px corners; major panels have 8px corners; pills are reserved for short status badges. Space on the existing 4px scale. Prefer dividers and spacing inside a panel to nested borders.

Tailor is **settings-first**: its always-visible settings summary comes before the job description and progress, followed by results and recent runs. Apply places compact settings and operation progress above independent tables: a "Needs your review" table first (only when applications are waiting on the applicant), then working applications, then the archived disclosure. Archive state is organization, not application status. Profile has Personal information, Resume content, and Application details with separate saves. Application details use their own route and saved artifacts; opening them never triggers generation or filling.

Tables use a consistent selection column, sortable headings where available, one primary row action, an overflow menu, a contextual selection toolbar, and pagination above and below. “Select this page” never reaches other pages or tables. On narrow screens, show readable record cards from the same rows and selection state. Menus render outside clipped table containers and return focus on dismissal. Search/filter/sort/page state lives in URL parameters so navigation restores context.
