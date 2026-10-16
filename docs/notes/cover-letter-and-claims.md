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
- **Tests:** `test_letter_paragraphs_drop_the_bullet_hanging_indent` and `test_letter_blocks_are_separated_but_address_stays_tight` in `tests/document/test_cover_template.py`.
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

## Cover-letter settings: letterhead and blocks (2026-10-11)

- **Decision:** letterhead and block choices live in `templates/cover_settings.json` (`document/cover_settings.py`), not in `WorkspaceSettings`: they describe the letter's layout, belong beside the cover template, and must be readable by the CLI and both web render paths (`render_cover_letter` has no web settings object). Workspace clone copies the file.
- **Decision:** toggles are applied at render (`blocks` in the Jinja context), never at build — `ensure_cover_template` does not watch settings, and a rebuild per toggle would be wasted work. The default letterhead became "same as resume", replacing `COVER_CONTACT_FIELDS` (location/email/phone): letters now show LinkedIn/GitHub when the resume does, as the user asked for.
- **Decision:** the subject line is code-filled from the posting title — no prompt change, no cache-key change. The subject block defaults off, so a default letter prints exactly as before.
- **Fix found while verifying in Word:** a table-layout resume's cover template was a corrupt `.docx` (cells emptied of every `w:p`, and letter paragraphs appended after the body `w:sectPr`). python-docx parsed it, so the tests never saw it. Also: such a letterhead now keeps the resume's side margins (its fixed column widths overflowed 1" margins) and the body is indented to the table's text edge.

---

- Own cover letter (Phase 6): tokens, not guessing — a letter has no structure the analyzer could find reliably (the body is just paragraphs), so the person marks where each part goes. The starter is the generated letter rendered with sentinels, so the easiest path is "download, restyle, upload".
- The starter renders with the subject line on, which carries the gap under the address; the greeting is given the same space-before so it keeps the gap when the subject is off (found in the visual check).
- Per-entry custom lines (a "Tools used:" line inside each job) were not built in this phase: they need a new per-entry data field, editor inputs and builder support inside entry prototypes. Left for a later change.

---

- **2026-10-11 — Length aim vs hard band.** Told 300–380 words, gemma4 wrote a median 258
  and 266 of 268 letters failed the band even after the retry: a spent call that fixed
  nothing. The model is now asked for `COVER_WORD_AIM` (270–380) with the structure sized
  in sentences per paragraph (opening 2–3, two bodies of 3–4, close 2;
  `_COVER_PROMPT_VERSION` 5); outside the aim is a warning only, and the retry fires on
  length only outside `COVER_WORD_BAND` (230–400). Other hard offenders still retry.

## Leftover guard offenders are reported by kind (2026-10-16)

After the one retry, `_GuardResult.leftover_warnings` splits what remains: unsupported
numbers or claims read "Unsupported claims remain after retry: ..."; a word count
outside the hard band reads "Letter is N words (band lo-hi)"; long dashes and "I" runs
read "Style issues remain: ...". The old single "Guard issues remain" line called a
too-short letter an unsupported claim. Long dashes the mechanical fix replaced are not
reported as leftovers. Retry behaviour is unchanged (`hard_offenders` still drives it).

Expansion (`expand._accept_bullets`) now runs `bullet_checks.delegated_authorship` and
warns once per entry when a bullet claims first-hand work its source credits to a
vendor or contractor. Report only: no retry, no drop (the paste text is advisory).
