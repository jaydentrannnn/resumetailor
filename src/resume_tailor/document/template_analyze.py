"""Deterministic structural analysis of a single-column resume DOCX.

Produces ranked mapping suggestions and blocking compatibility issues. Never mutates
the document and never calls an LLM — the confirmed mapping is what `template_build`
consumes.
"""

from __future__ import annotations

import docx

from .. import config
from . import (
    analysis_types,
    contact_detect,
    docx_text,
    entry_structure,
    profile_validation,
    section_mapping,
    table_layout,
)
from .template_profile import (
    ContactMapping,
    DetectedSection,
    EnabledSections,
    HeadingPrototype,
    NormalizationFlags,
    SpacingProfile,
    TemplateProfile,
)


def _load_paras(doc) -> list[analysis_types._Para]:
    """Flatten document body paragraphs — including any inside tables — into indexed
    `_Para` records, via `docx_text.iter_document_paragraphs`.

    THE id space: every `CharSpan.paragraph_id` and every bare `*_paragraph_id` field
    in `template_profile.py` is an index into this exact sequence.
    `template_build._para_by_id` must enumerate identically — see that function.
    """
    out: list[analysis_types._Para] = []
    for i, (paragraph, location) in enumerate(docx_text.iter_document_paragraphs(doc)):
        text = paragraph.text or ""
        out.append(
            analysis_types._Para(
                id=i,
                paragraph=paragraph,
                text=text,
                is_bullet=analysis_types.is_bullet(paragraph),
                has_tab=analysis_types.has_tab(paragraph),
                has_hyperlink=analysis_types.has_hyperlink(paragraph),
                runs=list(paragraph.runs),
                location=location,
            )
        )
    return out


def analyze_docx(
    path: str | bytes | None = None,
    *,
    raw: bytes | None = None,
    overrides: dict[int, str | None] | None = None,
) -> analysis_types.AnalyzeResult:
    """Analyze a DOCX from a filesystem path or in-memory bytes.

    Prefer `raw=` for uploads (hash is of the exact bytes). Path mode reads the file
    and hashes those bytes.

    `overrides` maps a paragraph id to a user-confirmed kind (`"experience"`,
    `"education"`, `"projects"`, `"skills"`, `"list"`) or `None` to say "this is not a
    section, regardless of what the heuristics think" — see `_analyze_document`.
    """
    import tempfile
    from pathlib import Path

    if raw is not None:
        digest = analysis_types.sha256_bytes(raw)
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            doc = docx.Document(str(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)
    elif path is not None:
        path_obj = Path(path)
        digest = analysis_types.sha256_bytes(path_obj.read_bytes())
        doc = docx.Document(str(path_obj))
    else:
        raise ValueError("analyze_docx requires path or raw bytes")

    return _analyze_document(doc, digest, overrides=overrides)


def _analyze_document(
    doc, digest: str, *, overrides: dict[int, str | None] | None = None
) -> analysis_types.AnalyzeResult:
    """Run structural analysis on an open Document.

    `overrides` (paragraph id -> forced kind, or `None` for "not a section") lets the
    wizard's remap step correct a specific heading's classification without touching
    any other paragraph's — see the "user-confirmed" branch in
    `_Analyzer._heading_candidate`. Every heuristic gate (fingerprint corroboration,
    has-tab exclusion, `_introduces_content`, …) is a signal for *guessing*; a user
    override is not a guess, so it bypasses all of them.
    """
    return _Analyzer(doc, digest, overrides).run()


class _Analyzer(section_mapping._SectionMapper):
    """One `_analyze_document` pass.

    Each step reads the document's paragraphs and appends to the shared `issues` and
    `field_candidates` lists, in document-analysis order (the order the wizard shows).
    """

    def __init__(self, doc, digest: str, overrides: dict[int, str | None] | None) -> None:
        self.doc = doc
        self.digest = digest
        self.issues: list[analysis_types.Issue] = []
        self.paras = _load_paras(doc)
        self.overrides = overrides or {}
        self.field_candidates: list[analysis_types.FieldCandidate] = []

    def run(self) -> analysis_types.AnalyzeResult:
        paras = self.paras
        # Computed early (usually this sits right before the heading-detection loop below)
        # specifically so `classify_table_layout` can use the same corroboration signal:
        # a short all-caps paragraph that merely looks heading-shaped (a state abbreviation
        # like "CA" in a location cell, say) must not be mistaken for a sidebar heading
        # just because nothing else disqualifies it — the fingerprint check is what tells
        # the two apart, since only real headings recur with matching formatting.
        self.heading_fp_classes = entry_structure._heading_classes(paras)
        self.table_shape = self._check_document_shape()
        paragraph_infos = [
            analysis_types.ParagraphInfo(
                id=p.id,
                text=p.text,
                is_bullet=p.is_bullet,
                is_heading_candidate=bool(entry_structure._classify_heading(p.text)[0]),
                has_tab=p.has_tab,
                has_hyperlink=p.has_hyperlink,
                run_count=len(p.runs),
                preview=(p.text[:120] + ("…" if len(p.text) > 120 else "")),
            )
            for p in paras
        ]

        self.section_candidates, self.by_kind = _resolve_section_bodies(
            self._detect_headings(), paras
        )
        # One representative heading per kind — the first found, in document order —
        # whose `heading_paragraph_id`/`heading_text` become that kind's mapping fields
        # (what `template_build` anchors the kind's tagged prototype on). `combined_body`
        # pools every same-kind heading's body for prototype/bullet selection, so the
        # best entry can come from any of them, not only the first.
        self.section_by_key: dict[str, analysis_types.SectionCandidate] = {
            key: candidates[0] for key, candidates in self.by_kind.items()
        }
        self.combined_body: dict[str, list[analysis_types._Para]] = {
            key: [p for sec in candidates for p in paras[sec.body_start : sec.body_end]]
            for key, candidates in self.by_kind.items()
        }
        self._check_experience_present()
        self._detect_contact()
        self._check_manual_bullets()

        found = self.section_by_key
        self.enabled = EnabledSections(
            education="education" in found,
            experience="experience" in found,
            projects="projects" in found,
            skills="skills" in found,
            list_section="list" in found,
        )
        self.experience_mapping = self._map_experience() if "experience" in found else None
        self.education_mapping = self._map_education() if "education" in found else None
        self.projects_mapping = self._map_projects() if "projects" in found else None
        self.skills_mapping = self._map_skills() if "skills" in found else None
        self.list_mapping = self._map_list() if "list" in found else None
        for key in ("education", "projects", "skills"):
            if key not in found:
                self.issues.append(
                    analysis_types.Issue(
                        code=f"omit_{key}",
                        message=(
                            f"No {key.title()} section detected; it will be omitted from the "
                            "template."
                        ),
                        blocking=False,
                    )
                )

        blockers = [i for i in self.issues if i.blocking]
        suggested = None if blockers else self._suggest_profile()
        return analysis_types.AnalyzeResult(
            source_sha256=self.digest,
            paragraphs=paragraph_infos,
            sections=self.section_candidates,
            suggested_profile=suggested,
            field_candidates=self.field_candidates,
            issues=self.issues,
            ready=suggested is not None and not blockers,
        )

    # -- whole-document checks ---------------------------------------------------------

    def _check_document_shape(self) -> table_layout.TableShape | None:
        doc, issues = self.doc, self.issues
        table_shape: table_layout.TableShape | None = None
        if analysis_types._document_has_tables(doc):
            table_shape, table_issues = table_layout.classify_table_layout(
                doc, self.paras, self.heading_fp_classes
            )
            issues.extend(table_issues)
        if analysis_types._document_has_textboxes(doc):
            issues.append(
                analysis_types.Issue(
                    code="textboxes",
                    message=(
                        "Document puts text inside text boxes, which usually means a "
                        "multi-column or sidebar layout. Only single-column body text is "
                        "supported."
                    ),
                    blocking=True,
                )
            )
        elif analysis_types._document_has_drawings(doc):
            issues.append(
                analysis_types.Issue(
                    code="decorative_drawing",
                    message=(
                        "Images, icons and lines are kept exactly as they are; only the text "
                        "around them is tailored."
                    ),
                    blocking=False,
                )
            )
        if len(self.paras) < 2:
            issues.append(
                analysis_types.Issue(
                    code="too_short",
                    message="Document needs at least a name line and a contact line.",
                    blocking=True,
                )
            )
        return table_shape

    def _check_experience_present(self) -> None:
        if "experience" in self.section_by_key:
            return
        # Blocking only when nothing else can carry entries: a first-year student's
        # Education + Projects (or Activities) resume is a complete template.
        has_other_entries = bool({"projects", "list"} & self.section_by_key.keys())
        self.issues.append(
            analysis_types.Issue(
                code="missing_experience",
                message=(
                    "No Experience section heading found. The template will show your "
                    "other sections; add an Experience heading in Word to include jobs."
                    if has_other_entries
                    else "Could not find an Experience / Work Experience section heading."
                ),
                blocking=not has_other_entries,
            )
        )

    def _check_manual_bullets(self) -> None:
        # Manual bullet glyph warning (non-blocking unless no native bullets in experience).
        for p in self.paras:
            stripped = p.text.lstrip()
            if stripped.startswith(("•", "●", "○", "-", "–", "—")) and not p.is_bullet:
                self.issues.append(
                    analysis_types.Issue(
                        code="manual_bullets",
                        message=(
                            f"Paragraph {p.id} looks like a bullet but is not a Word list "
                            "item. Convert lists to real bullets in Word/Google Docs before "
                            "uploading."
                        ),
                        blocking=False,
                    )
                )
                return

    # -- headings ----------------------------------------------------------------------

    def _detect_headings(self) -> list[analysis_types.SectionCandidate]:
        """Every section heading in the document, in order.

        Alias-matched or structurally inferred, without deduplicating by kind. A resume
        may have any number of experience-shaped sections (WORK EXPERIENCE, LEADERSHIP
        EXPERIENCE, OTHER ACTIVITIES, …); each becomes its own candidate, and `run` pools
        same-kind candidates together when picking that kind's prototype entry.

        Structure-first corroboration (see `_heading_classes`'s docstring): a formatting
        signature shared by several short, content-introducing paragraphs is what a
        resume's own section headings typically look like. The alias table only *names* a
        heading's kind; `heading_fp_classes` is what actually decides whether the
        structural fallback gets to guess at all, and downgrades a merely-plausible text
        match that nothing else in the document agrees with. Empty when nothing qualifies
        (too few candidates, or no repeated formatting) — every use degrades to text-only
        behavior in that case, exactly as if the feature did not exist.
        """
        raw_headings: list[analysis_types.SectionCandidate] = []
        for p in self.paras:
            if p.is_bullet or not p.text.strip() or entry_structure._is_chrome(p.text):
                continue
            candidate = self._heading_candidate(p)
            if candidate is not None:
                raw_headings.append(candidate)
        raw_headings.sort(key=lambda s: s.heading_paragraph_id)
        return raw_headings

    def _heading_candidate(self, p: analysis_types._Para) -> analysis_types.SectionCandidate | None:
        paras, heading_fp_classes = self.paras, self.heading_fp_classes
        if p.id in self.overrides:
            forced = self.overrides[p.id]
            if forced is None:
                return None  # user confirmed: not a section, regardless of the heuristics
            return analysis_types.SectionCandidate(
                key=forced,
                heading_paragraph_id=p.id,
                heading_text=p.text.strip(),
                body_start=p.id + 1,
                body_end=len(paras),
                confidence=1.0,
                aliases_matched="user-confirmed",
            )
        key, conf, alias = entry_structure._classify_heading(p.text)
        # `p.id >= 2` keeps the structural fallback off the name/contact lines — both are
        # short, and a name in particular is very often all-caps or Title Case, which
        # would otherwise misclassify paragraph 0 as a heading. Paragraphs 0/1 are name
        # and contact everywhere else in this codebase (`build_name`/`build_contact`
        # legacy mode, `content_paras[0]`/`[1]`); an alias match is unaffected by this
        # guard since a name or contact line never happens to equal a known alias.
        if key is None and p.id >= 2 and entry_structure._looks_like_heading(p.text):
            key = self._structural_heading_kind(p)
            if key is None:
                return None
            conf, alias = 0.4, "structural"
        if key is None:
            return None
        uncorroborated = (
            bool(heading_fp_classes) and entry_structure._fingerprint(p) not in heading_fp_classes
        )
        # The <=0.6-confidence tiers — a keyword appearing anywhere in the lowercased
        # text, with no case requirement at all — are weak enough that an ordinary
        # entry header matches them exactly like a real heading would: a job title
        # ("Experience Designer") right under a company/dates line, or a later entry's
        # own tab-aligned "Name\tDate" header (an "Advocate of Sexual Education in
        # School\t2022" activity inside "OTHER ACTIVITIES" matching the "education"
        # keyword). Fingerprint corroboration alone can't screen these out: an entry
        # header's formatting can land in the same class as the document's real
        # headings just as easily as a genuine heading styled slightly differently
        # ("SKILLS & Interests" mixing case) can fail to. Two structural, position-based
        # signals tell the two apart instead: a real section heading is never itself
        # tab-aligned with a trailing date (`_heading_classes`'s own candidate filter
        # already assumes this), and never sits immediately after another entry's own
        # header line. Exact alias matches (conf == 1.0, e.g. literally "EDUCATION")
        # are trusted on text alone regardless of position or formatting.
        if conf < 1.0 and (
            analysis_types._has_tab_like(p)
            or entry_structure._immediately_follows_entry_header(p, paras)
        ):
            return None
        if conf < 1.0 and uncorroborated:
            conf = min(conf, 0.4)
            self.issues.append(
                analysis_types.Issue(
                    code="heading_formatting_mismatch",
                    message=(
                        f"{p.text.strip()!r} (paragraph {p.id}) looks like a {key} "
                        "heading by its text, but its formatting does not match the "
                        "document's other section headings. Confirm this is really a "
                        "section heading."
                    ),
                    blocking=False,
                )
            )
        return analysis_types.SectionCandidate(
            key=key,
            heading_paragraph_id=p.id,
            heading_text=p.text.strip(),
            body_start=p.id + 1,
            body_end=len(self.paras),
            confidence=conf,
            aliases_matched=alias,
        )

    def _structural_heading_kind(self, p: analysis_types._Para) -> str | None:
        """The kind of an unaliased heading-shaped line, or None when it is not a heading.

        No alias matched, but this looks like a heading. A user can name a section
        anything, so no fixed alias list can be complete.

        Two hard gates, both required: the line must actually introduce something (a
        bullet, or a tab-aligned entry header) before the next heading-shaped line — a
        "PROFESSIONAL SUMMARY" followed only by a sentence of prose introduces nothing and
        is not a section. And when the document has a detectable heading-formatting class
        at all, an unaliased candidate must belong to it — this is the "guess" path with
        zero other evidence, so structural corroboration is required here, not just
        preferred.
        """
        paras, heading_fp_classes = self.paras, self.heading_fp_classes
        if not entry_structure._introduces_content(p, paras, frozenset(heading_fp_classes)):
            return None
        if heading_fp_classes and entry_structure._fingerprint(p) not in heading_fp_classes:
            return None
        # Default to "experience" — the common case for an unnamed achievements-with-
        # employer section — unless it is immediately followed by bullets with no entry
        # header, which is a plain list-shaped section (certifications, awards, …).
        next_content = next(
            (q for q in paras if q.id > p.id and not entry_structure._is_chrome(q.text)), None
        )
        return "list" if next_content is not None and next_content.is_bullet else "experience"

    # -- name and contact --------------------------------------------------------------

    def _detect_contact(self) -> None:
        issues, paras = self.issues, self.paras
        # Name + contact: everything above the first detected heading, classified by regex
        # — see `_detect_name_and_contact` for why "first two non-heading paragraphs" isn't
        # enough once a table layout spreads the contact block across several paragraphs.
        first_heading_id = (
            self.section_candidates[0].heading_paragraph_id if self.section_candidates else None
        )
        self.name_id, self.contact_para, self.contact_slots, unmapped_contact_paras = (
            contact_detect._detect_name_and_contact(paras, first_heading_id)
        )

        # A name/contact block in the page header (Insert → Header) is kept as uploaded.
        body_before_heading = first_heading_id is None or any(
            p.text.strip() and not p.is_bullet for p in paras if p.id < first_heading_id
        )
        header_text = entry_structure.header_identity_text(self.doc)
        self.contact_in_header = (
            self.contact_para is None
            and not self.contact_slots
            and bool(
                analysis_types._EMAIL_RE.search(header_text)
                or analysis_types._PHONE_RE.search(header_text)
            )
        )
        self.name_in_header = self.contact_in_header and not body_before_heading
        if self.contact_in_header:
            issues.append(
                analysis_types.Issue(
                    code="contact_in_header",
                    message=(
                        "Your name and contact details are in the page header. They'll be "
                        "kept exactly as they are and won't change when you tailor."
                        if self.name_in_header
                        else "Your contact details are in the page header. They'll be kept "
                        "exactly as they are and won't change when you tailor."
                    ),
                    blocking=False,
                )
            )
        elif self.contact_para is None and not self.contact_slots:
            issues.append(
                analysis_types.Issue(
                    code="missing_contact",
                    message="Could not find a contact line after the name.",
                    blocking=True,
                )
            )
        for p in unmapped_contact_paras:
            issues.append(
                analysis_types.Issue(
                    code="contact_unmapped_paragraph",
                    message=(
                        f"{p.text.strip()!r} (paragraph {p.id}) is part of the contact "
                        "block but doesn't look like an email, phone, location, or "
                        "profile link. It will stay a literal in the template."
                    ),
                    blocking=False,
                )
            )

    # -- the suggested profile ---------------------------------------------------------

    def _suggest_profile(self) -> TemplateProfile | None:
        """The profile the wizard proposes, or None when the analysis cannot build one."""
        enabled = self.enabled
        if not (
            (self.experience_mapping is not None or not enabled.experience)
            and (enabled.experience or enabled.projects or enabled.list_section)
            and (self.contact_para is not None or self.contact_slots or self.contact_in_header)
        ):
            return None
        contact: ContactMapping | None = None  # stays None for a header contact block
        if self.contact_slots:
            contact = ContactMapping(
                paragraph_id=self.contact_slots[0].paragraph_id,
                slots=self.contact_slots,
            )
        elif self.contact_para is not None:
            contact = ContactMapping(
                paragraph_id=self.contact_para.id,
                field_order=contact_detect._contact_field_order(self.contact_para.text),
                separator=contact_detect._contact_separator(self.contact_para.text),
            )

        # Generic mode is needed the moment fixed mode could not represent what was found:
        # more than one heading of some kind (two experience-shaped sections cannot both
        # keep their own title/position under one hard-coded heading), a `list`-kind
        # section (fixed mode has no such prototype at all), or a table layout (always
        # generic — see `TemplateProfile.layout`'s docstring). Otherwise today's exact
        # single-heading-per-kind case stays on fixed mode, byte-identical to before this
        # existed.
        is_table_layout = self.table_shape is not None
        needs_generic = (
            is_table_layout
            or "list" in self.by_kind
            or any(len(v) > 1 for v in self.by_kind.values())
        )
        detected_sections: list[DetectedSection] = []
        heading_prototype: HeadingPrototype | None = None
        spacing = SpacingProfile()
        if needs_generic:
            detected_sections = _detected_sections(self.section_candidates)
            heading_prototype = HeadingPrototype(
                paragraph_id=self.section_candidates[0].heading_paragraph_id
            )
            # A table layout's inter-section gaps come from heading rows' own paragraph
            # spacing and dedicated spacer rows, not counted blank paragraphs —
            # `_detect_spacing`'s chrome-run model doesn't translate, and
            # `TemplateProfile` rejects a table-layout profile carrying spacing donors.
            spacing = (
                SpacingProfile() if is_table_layout
                else contact_detect._detect_spacing(self.paras, self.section_candidates)
            )

        return TemplateProfile(
            source_sha256=self.digest,
            name_paragraph_id=self.name_id,
            contact=contact,
            name_in_header=self.name_in_header,
            contact_in_header=self.contact_in_header,
            enabled=enabled,
            experience=self.experience_mapping if enabled.experience else None,
            education=self.education_mapping if enabled.education else None,
            projects=self.projects_mapping if enabled.projects else None,
            skills=self.skills_mapping if enabled.skills else None,
            list_section=self.list_mapping if enabled.list_section else None,
            normalization=NormalizationFlags(),
            warnings=[i.message for i in self.issues if not i.blocking],
            section_mode="generic" if needs_generic else "fixed",
            sections=detected_sections,
            heading_prototype=heading_prototype,
            spacing=spacing,
            layout="table" if is_table_layout else "paragraph",
            paragraph_count=len(self.paras),
        )


def _resolve_section_bodies(
    raw_headings: list[analysis_types.SectionCandidate], paras: list[analysis_types._Para]
) -> tuple[list[analysis_types.SectionCandidate], dict[str, list[analysis_types.SectionCandidate]]]:
    """Each heading's body span and entry/bullet counts, plus the headings by kind.

    `body_end` is the next heading OF ANY KIND, so an embedded same-kind sub-heading
    (e.g. "LEADERSHIP EXPERIENCE" after "WORK EXPERIENCE") is never mis-read as an entry
    header by `_split_entries` — each heading's slice already excludes every other
    heading paragraph by construction.
    """
    section_candidates: list[analysis_types.SectionCandidate] = []
    by_kind: dict[str, list[analysis_types.SectionCandidate]] = {}
    for i, sec in enumerate(raw_headings):
        end = (
            raw_headings[i + 1].heading_paragraph_id
            if i + 1 < len(raw_headings)
            else len(paras)
        )
        body = paras[sec.body_start : end]
        entries = entry_structure._split_entries(body)
        bullets = sum(1 for x in body if x.is_bullet)
        resolved = sec.model_copy(
            update={"body_end": end, "entry_count": len(entries), "bullet_count": bullets}
        )
        section_candidates.append(resolved)
        by_kind.setdefault(resolved.key, []).append(resolved)
    return section_candidates, by_kind




def _detected_sections(
    section_candidates: list[analysis_types.SectionCandidate],
) -> list[DetectedSection]:
    """Generic-mode sections, one per heading, with ids unique by heading-text slug."""
    detected: list[DetectedSection] = []
    seen_ids: set[str] = set()
    for sec in section_candidates:
        base = config.slugify(sec.heading_text) or sec.key
        candidate_id = base
        suffix = 2
        while candidate_id in seen_ids:
            candidate_id = f"{base}-{suffix}"
            suffix += 1
        seen_ids.add(candidate_id)
        detected.append(
            DetectedSection(
                id=candidate_id,
                title=sec.heading_text,
                kind=analysis_types._TO_GENERIC_KIND.get(sec.key, sec.key),  # type: ignore[arg-type]
                heading_paragraph_id=sec.heading_paragraph_id,
            )
        )
    return detected


def validate_profile_against_doc(
    profile: TemplateProfile,
    *,
    raw: bytes,
) -> list[analysis_types.Issue]:
    """Re-check a confirmed profile against the exact upload bytes before install."""
    digest = analysis_types.sha256_bytes(raw)
    if profile.source_sha256 != digest:
        return [
            analysis_types.Issue(
                code="hash_mismatch",
                message=(
                    "Mapping was confirmed against a different file than the one being "
                    "installed. Re-analyze the upload."
                ),
                blocking=True,
            )
        ]
    result = analyze_docx(raw=raw)
    return profile_validation._ProfileValidator(profile, {p.id: p for p in result.paragraphs}).run()
