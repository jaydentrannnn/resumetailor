# Cover letter & claim checks — implementation notes

Covers: cover letter stage, its guard and template, Documents card, check_claims / verify-claim.

Entries are in original log order (roughly chronological); later entries supersede
earlier ones. Cross-check any number against the code.

## 2026-08-29 — Cover letter stage

- **Decision:** Add an opt-in seventh LLM stage (`coverletter.draft_letter`) after skills; derive `cover_template.docx` from `original_export.docx`; editable `cover_style` with locked core; guards in code (numbers, narrowed claim sentences, verbatim JD fields, AI tells, consecutive I, word band) with one targeted retry; persist `bullets.json` and `backends.json` per job for regenerate on a restarted server via `config.pinned_specs`.
- **Why:** Cover letters need the same fabrication discipline as bullets but allow more connective prose; company/addressee must not be invented when absent from the posting; regeneration must not depend on in-process `config._ACTIVE`.
- **Tradeoff:** Guard is narrower than `rewrite` (claim sentences only); word-count band is the primary length control with a one-page PDF render as safety net only; off by default (`cover_letter: false`).
- **Follow-up:** Application-prompt responses remain deferred per plan.

## 2026-08-29 — Cover letter opt-in placement and failure visibility

- **Decision:** Moved the `Generate cover letter` toggle out of the collapsed **Advanced** panel into the always-visible **Output** fieldset on the Tailor tab, and made a failed cover stage append its reason to `job.report.warnings` in addition to emitting a progress event.
- **Why:** The toggle was the 3rd of ~10 toggles behind a collapsed disclosure, so the feature read as missing. Separately, a cover-stage exception is swallowed (bonus artifact, never fails the job) and renders no card, so the only signal was a transient progress event: the user saw two missing files and nothing explaining why.
- **Tradeoff:** `Output` now mixes a stage opt-in with page/entry counts; accepted because the cover letter is a headline deliverable, not an advanced tuning knob. `cover_style` stays in Advanced beside the other style editors.
- **Verified:** `build_cover_template` + `render_letter` both succeed against the real `original_export.docx` (placeholders all substituted, no leftover Jinja tags); the missing `cover.docx`/`cover.pdf` were solely because `cover_letter` was false.

## 2026-08-29 — Cover letter inherited the resume bullet's hanging indent

- **Bug:** Every letter paragraph (date, inside address, salutation, body, closing, signature) rendered inset half an inch with a negative first line, and with no space between blocks. Measured on the rendered PDF: first lines at x=61.3, wrapped lines at x=79.3, against a page margin of x=43.2.
- **Cause:** `cover_template._find_body_donor` picks the first *numbered* paragraph after the letterhead as the formatting donor, and `_strip_numbering` removed only `w:numPr`. The bullet's `w:ind w:left="720" w:hanging="360"` survived on every clone, as did its zero space-after (resume bullets sit flush against each other).
- **Fix:** `_clone_donor_paragraph` now zeroes `left`/`right`/`first_line` indent and sets explicit block spacing. Kept the bullet donor rather than switching to a plain body paragraph: bullets are the one paragraph kind guaranteed to carry body-weight prose formatting, where an entry header can be bold or carry tab stops.
- **Spacing:** one blank line of the donor's own font size (`_donor_font_size`, read from the first run then the `w:pPr/w:rPr/w:sz` paragraph mark, defaulting to 10pt) rather than a hardcoded gap. Not uniform: the inside address is a tight stack and so are closing/signature, so the gap before the salutation is carried by the salutation's own space-before, because the address line repeats in a `{%p for %}` loop and cannot space only its last iteration.
- **Why python-docx's `paragraph_format`** instead of appending XML: its `get_or_add_ind`/`get_or_add_spacing` insert into `w:pPr` in OOXML schema order. Hand-appended `w:ind`/`w:spacing` parse fine but Word rejects the file.
- **Note:** `first_line_indent` is set to `0`, not `None` — `None` removes the element and lets the underlying style's hanging indent apply again.
- **Tests:** `test_letter_paragraphs_drop_the_bullet_hanging_indent` and `test_letter_blocks_are_separated_but_address_stays_tight` in `tests/test_cover_template.py`.
- **Not a bug:** the resume itself renders fine. `tailored.docx`/`tailored.pdf` are written on every run and `GET /api/jobs/{id}/preview.pdf` serves a valid 1-page `application/pdf` with `Content-Disposition: inline`. `cover-letter.pdf` is served `attachment` and the Cover letter card has no inline iframe, so the rendered letter can only be seen by downloading it — possible follow-up for parity with `ResultPreview`.

## 2026-08-29 — Cover letter guard, template layout, and inline preview

- **Decision:** License resume entry-header proper nouns for cover-letter claim sentences via `_resume_context_bullet` appended in `_source_bullets` (not by widening `rewrite._check_fabrication`); set cover margins to `COVER_MARGIN_INCHES = 1.0`, body line spacing to 1.15, letterhead contact to `COVER_CONTACT_FIELDS` (location/email/phone), clone the resume section-heading rule onto the contact paragraph; stamp `cover_template.meta.json` with `_BUILDER_VERSION` so code changes rebuild stale templates; add `GET /api/jobs/{id}/cover-letter/preview.pdf` (inline) and an iframe on `CoverLetterCard` with `previewKey` cache-busting on regenerate; drop `"align with"` from `_AI_PHRASES`.
- **Why:** Employer names like "Age of Learning Inc." live on entry headers, not bullet text, so the fabrication guard falsely retried and produced short defensive letters; the cover template inherited resume cram margins and bullet single-spacing; builder-version staleness matched the indent-fix trap; the card showed plain text only because `cover-letter.pdf` was attachment-only.
- **Tradeoff:** JD vocabulary is deliberately *not* licensed for claim sentences (numbers still check the JD); letterhead drops LinkedIn/GitHub by field filter, not by re-tagging the template; preview iframe only mounts when `has_pdf` is true.
- **Follow-up:** Rebuild `cover_template.docx` per workspace after deploy (`python scripts/build_cover_template.py` or any code path that calls `ensure_cover_template`).

## 2026-08-29 — Single tabbed PDF preview (resume vs cover letter)

- **Decision:** Replaced separate resume/cover iframes with one `OutputPreview` at the bottom of the Tailor page. When a cover-letter PDF exists, tabs switch between resume and cover; only the active tab mounts an iframe.
- **Why:** Chrome/Edge on Windows use a singleton PDF plugin — two embedded `*.pdf` iframes on one page often leave one blank.
- **Tradeoff:** Both documents are not visible simultaneously; user switches tabs. Cover letter card keeps text/copy/regenerate; PDF lives in the shared preview block.

## 2026-08-29 — Merged Documents card (resume + cover letter)

- **Decision:** Replaced the separate `CoverLetterCard` (row 5) and `OutputPreview` (row 7) with one `DocumentsCard` at row 7. Tabs switch between **Tailored resume** and **Cover letter**; each tab shows that document's download actions, a single PDF iframe (or a PDF-unavailable note on the cover tab), and cover-only extras (warnings, letter text, regenerate). Resume `.pdf`/`.docx` buttons moved out of `ReportCard` into the resume tab.
- **Why:** Full-merge layout the user asked for; still only one iframe mounted at a time (browser PDF plugin singleton on Windows).
- **Tradeoff:** Cover letter content is no longer visible above the report/skills tiles — everything document-related lives in one bottom section. `CoverLetterPanel` split into `CoverLetterActionBar` + `CoverLetterDetails` so regenerate state is not duplicated.
- **Follow-up:** After frontend source changes, run `npm run build` (or `docker compose up --build`) — the prior tabbed preview existed only in source while `dist/` was stale.

## 2026-08-29 — Documents card hidden on lg grid

- **Bug:** `DocumentsCard` and `RunHistoryPanel` both used `lg:row-start-7`, so in two-column layout they occupied the same grid cell; history painted on top and hid the documents preview. Single-column mode ignores explicit row pins, so both stacked visibly.
- **Fix:** Renumbered results rows after removing the cover-letter card from row 5: skills/report → row 5, documents → row 6, history → row 7 (unchanged).

## 2026-09-19 — `check_claims` / `POST /api/verify-claim` for application answers

- **Decision:** Add `coverletter.check_claims` (public façade over `_source_bullets`,
  `_claim_fabrication_offenders(first_person_only=False)`, `_numbers_not_in_source`) and
  `POST /api/verify-claim`. Keyword-only `first_person_only: bool = True` on
  `_claim_fabrication_offenders` keeps the cover-letter path byte-identical.
- **Why:** Application answers are often resume-voice ("Led a team…") with no first-person
  pronoun; the cover-letter filter would skip them and let invented tech sail through.
  Extends the fabrication-guard property to agent-written free text outside the pipeline.
- **Spec delta:** `_resume_context_bullet` is no longer cover-letter-only — also used by
  `check_claims`. Helpers stay private; one new public symbol.
- **Tradeoff:** Checking every sentence is stricter than cover letters (company-description
  prose would also be checked) — correct for `verify_claim`'s input contract.
