"""Validating a saved template profile against the document it claims to describe."""

from __future__ import annotations

from . import analysis_types, docx_text
from .template_profile import (
    CharSpan,
    EducationMapping,
    ExperienceMapping,
    OptionalSpan,
    ProjectsMapping,
    SkillsMapping,
    TemplateProfile,
)


class _ProfileValidator:
    """Structural re-validation of a confirmed profile: required paragraphs must still
    exist and every mapped span must fit."""

    def __init__(
        self, profile: TemplateProfile, para_by_id: dict[int, analysis_types.ParagraphInfo]
    ) -> None:
        self.profile = profile
        self.para_by_id = para_by_id
        self.issues: list[analysis_types.Issue] = []

    def run(self) -> list[analysis_types.Issue]:
        profile, issues = self.profile, self.issues
        if not profile.name_in_header and profile.name_paragraph_id not in self.para_by_id:
            issues.append(
                analysis_types.Issue(
                    code="bad_name",
                    message=f"Name paragraph {profile.name_paragraph_id} is out of range.",
                    blocking=True,
                )
            )
        if profile.contact is not None and profile.contact.paragraph_id not in self.para_by_id:
            issues.append(
                analysis_types.Issue(
                    code="bad_contact",
                    message=f"Contact paragraph {profile.contact.paragraph_id} is out of range.",
                    blocking=True,
                )
            )
        if not (
            profile.enabled.experience or profile.enabled.projects or profile.enabled.list_section
        ):
            issues.append(
                analysis_types.Issue(
                    code="experience_required",
                    message="Keep at least one of Experience, Projects or a list section enabled.",
                    blocking=True,
                )
            )
        if profile.enabled.experience and profile.experience is not None:
            self._check_experience(profile.experience)
        if profile.enabled.education and profile.education is not None:
            self._check_education(profile.education)
        if profile.enabled.projects and profile.projects is not None:
            self._check_projects(profile.projects)
        if profile.enabled.skills and profile.skills is not None:
            self._check_skills(profile.skills)
        if profile.section_mode == "generic":
            self._check_generic_sections()
        return issues

    # -- per-section -------------------------------------------------------------------

    def _check_fields(self, spans: list[tuple[str, CharSpan]]) -> None:
        for label, span in spans:
            self._check_span(span, label)
        self._check_no_overlap(spans)

    def _check_experience(self, exp: ExperienceMapping) -> None:
        exp_spans = _present_spans(exp.header.fields)
        if exp.title.present and exp.title.span is not None:
            exp_spans.append(("title", exp.title.span))
        self._check_fields(exp_spans)
        self._check_bullet(exp.bullet_paragraph_id, "experience bullet prototype")
        self._check_header_is_entry_start(
            exp.header.header_paragraph_id, "experience header prototype"
        )
        exp_dates = exp.header.fields.get("dates")
        if exp_dates is not None and exp_dates.present:
            self._check_date_span(exp_dates.span, "experience dates")

    def _check_education(self, edu: EducationMapping) -> None:
        self._check_fields(_present_spans(edu.header.fields))
        self._check_bullet(edu.degree_paragraph_id, "education degree paragraph", strict=False)
        if edu.detail_paragraph_id is not None:
            self._check_bullet(
                edu.detail_paragraph_id, "education detail paragraph", strict=False
            )
        self._check_header_is_entry_start(
            edu.header.header_paragraph_id, "education header prototype"
        )
        edu_dates = edu.header.fields.get("dates")
        if edu_dates is not None and edu_dates.present:
            self._check_date_span(edu_dates.span, "education dates")

    def _check_projects(self, proj: ProjectsMapping) -> None:
        proj_spans = _present_spans(proj.header.fields)
        if proj.link.present and proj.link.span is not None:
            proj_spans.append(("link", proj.link.span))
        self._check_fields(proj_spans)
        self._check_bullet(proj.bullet_paragraph_id, "project bullet prototype")
        self._check_header_is_entry_start(
            proj.header.header_paragraph_id, "project header prototype"
        )
        proj_date = proj.header.fields.get("date")
        if proj_date is not None and proj_date.present:
            self._check_date_span(proj_date.span, "project date")

    def _check_skills(self, skl: SkillsMapping) -> None:
        self._check_fields([("skills_label", skl.label_span), ("skills_body", skl.body_span)])
        if skl.prototype_paragraph_id not in self.para_by_id:
            self.issues.append(
                analysis_types.Issue(
                    code="bad_span",
                    message=(
                        f"skills prototype: paragraph {skl.prototype_paragraph_id} "
                        "is missing."
                    ),
                    blocking=True,
                )
            )

    def _check_generic_sections(self) -> None:
        profile, para_by_id, issues = self.profile, self.para_by_id, self.issues
        if (
            profile.heading_prototype is not None
            and profile.heading_prototype.paragraph_id not in para_by_id
        ):
            issues.append(
                analysis_types.Issue(
                    code="bad_heading_prototype",
                    message=(
                        f"heading_prototype: paragraph "
                        f"{profile.heading_prototype.paragraph_id} is out of range."
                    ),
                    blocking=True,
                )
            )
        for s in profile.sections:
            if s.heading_paragraph_id not in para_by_id:
                issues.append(
                    analysis_types.Issue(
                        code="bad_detected_section",
                        message=(
                            f"Detected section {s.id!r} ({s.title!r}): heading "
                            f"paragraph {s.heading_paragraph_id} is out of range."
                        ),
                        blocking=True,
                    )
                )
        for label, donor_ids in (
            ("spacing.before_heading", profile.spacing.before_heading),
            ("spacing.after_heading", profile.spacing.after_heading),
            ("spacing.between_entries", profile.spacing.between_entries),
        ):
            for donor_id in donor_ids:
                donor = para_by_id.get(donor_id)
                # Non-blocking: a stale or no-longer-chrome donor should degrade to a
                # narrower gap at build time, not block the whole install — a spacer is a
                # cosmetic fidelity nicety, not load-bearing content.
                if donor is None or not docx_text.is_chrome_text(donor.text):
                    issues.append(
                        analysis_types.Issue(
                            code="spacer_donor_missing",
                            message=(
                                f"{label}: donor paragraph {donor_id} is missing or no "
                                "longer a blank/rule line; it will be omitted."
                            ),
                            blocking=False,
                        )
                    )

    # -- single checks -----------------------------------------------------------------

    def _check_span(self, span: CharSpan | None, label: str) -> None:
        """Blocking issue when `span` is out of range or straddles a tab.

        The tab check matters because `_tag_mapped_header` treats a tab inside a mapped
        span as a hard error at build time (the tab is what keeps a date right-aligned);
        catching it here turns that failure into a readable install-time rejection
        instead of a build crash — or, before that fix existed, a silently garbled
        template.
        """
        if span is None:
            return
        para = self.para_by_id.get(span.paragraph_id)
        if para is None:
            self.issues.append(
                analysis_types.Issue(
                    code="bad_span",
                    message=f"{label}: paragraph {span.paragraph_id} missing.",
                    blocking=True,
                )
            )
            return
        if span.end > len(para.text):
            self.issues.append(
                analysis_types.Issue(
                    code="bad_span",
                    message=(
                        f"{label}: span [{span.start}:{span.end}] exceeds paragraph "
                        f"length {len(para.text)}."
                    ),
                    blocking=True,
                )
            )
            return
        if "\t" in para.text[span.start : span.end]:
            self.issues.append(
                analysis_types.Issue(
                    code="span_has_tab",
                    message=(
                        f"{label}: span [{span.start}:{span.end}] contains a tab. "
                        "Map date fields after the tab, not through it."
                    ),
                    blocking=True,
                )
            )

    def _check_no_overlap(self, spans: list[tuple[str, CharSpan]]) -> None:
        """Blocking issue when two mapped fields on the same paragraph overlap.

        Grouped by paragraph because header fields occasionally live off the header
        paragraph (a `date_paragraph_id` on its own line); those never collide.
        """
        by_paragraph: dict[int, list[tuple[str, CharSpan]]] = {}
        for label, span in spans:
            by_paragraph.setdefault(span.paragraph_id, []).append((label, span))
        for paragraph_id, entries in by_paragraph.items():
            ordered = sorted(entries, key=lambda e: e[1].start)
            for (label_a, span_a), (label_b, span_b) in zip(ordered, ordered[1:], strict=False):
                if span_b.start < span_a.end:
                    self.issues.append(
                        analysis_types.Issue(
                            code="overlapping_spans",
                            message=(
                                f"{label_a!r} and {label_b!r} both claim text in "
                                f"paragraph {paragraph_id}: {label_a} ends at "
                                f"{span_a.end}, {label_b} starts at {span_b.start}."
                            ),
                            blocking=True,
                        )
                    )

    def _check_bullet(self, paragraph_id: int | None, label: str, *, strict: bool = True) -> None:
        """Issue when a bullet-prototype paragraph is missing or not a list item.

        A missing paragraph always blocks. A non-list paragraph blocks only when
        `strict` — the experience/project bullet loop is the resume's main visual list
        content, where real Word numbering matters. Education's degree/detail role is not
        strict: `template_build.retarget_bullet` creates a paragraph's numbering
        properties rather than requiring them, so a plain degree line still builds fine
        and only needs a non-blocking heads-up (see `template_analyze`'s
        `education_bullets_not_list` issue, raised for the same reason at analyze time).
        """
        if paragraph_id is None:
            return
        para = self.para_by_id.get(paragraph_id)
        if para is None:
            self.issues.append(
                analysis_types.Issue(
                    code="bad_bullet",
                    message=f"{label}: paragraph {paragraph_id} is missing.",
                    blocking=True,
                )
            )
        elif not para.is_bullet:
            self.issues.append(
                analysis_types.Issue(
                    code="bullet_not_list",
                    message=f"{label}: paragraph {paragraph_id} is not a Word list item.",
                    blocking=strict,
                )
            )

    def _check_header_is_entry_start(self, paragraph_id: int, label: str) -> None:
        """Blocking issue when a header prototype paragraph is a bullet or blank — the
        mapping cannot possibly be pointing at a real entry header in that case."""
        para = self.para_by_id.get(paragraph_id)
        if para is None:
            return  # already reported by _check_span / the earlier existence checks
        if para.is_bullet or not para.text.strip():
            self.issues.append(
                analysis_types.Issue(
                    code="header_not_entry_start",
                    message=(
                        f"{label}: paragraph {paragraph_id} is "
                        f"{'a bullet' if para.is_bullet else 'blank'}, not an entry header."
                    ),
                    blocking=True,
                )
            )

    def _check_date_span(self, span: CharSpan | None, label: str) -> None:
        """Non-blocking warning when a span mapped to a date field does not itself
        look like a date — confirms the mapping actually landed on a date, not some
        other text that happened to survive detection."""
        if span is None:
            return
        para = self.para_by_id.get(span.paragraph_id)
        if para is None:
            return  # already reported by _check_span
        text = para.text[span.start : span.end]
        if not analysis_types._DATE_RE.search(text):
            self.issues.append(
                analysis_types.Issue(
                    code="date_span_not_date_shaped",
                    message=(
                        f"{label}: mapped span {text!r} does not look like a date. "
                        "Confirm this field is mapped correctly."
                    ),
                    blocking=False,
                )
            )

def _present_spans(fields: dict[str, OptionalSpan]) -> list[tuple[str, CharSpan]]:
    """(field name, span) pairs for mapped fields that are actually present."""
    return [
        (name, field.span)
        for name, field in fields.items()
        if field.present and field.span is not None
    ]
