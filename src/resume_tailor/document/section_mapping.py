"""Per-kind prototype mapping for the template analyzer: experience, education,
projects, skills and list sections, plus the date and consistency issues they raise.

`_SectionMapper` is a mixin of `template_analyze._Analyzer`; it reads the analyzer's
detection state (declared below) and appends to its issues and field candidates.
"""

from __future__ import annotations

from . import (
    analysis_types,
    entry_structure,
    field_candidates,
    header_fields,
)
from .template_profile import (
    EducationMapping,
    EnabledSections,
    ExperienceMapping,
    ListMapping,
    OptionalSpan,
    ProjectsMapping,
    SkillsMapping,
)


class _SectionMapper:
    issues: list[analysis_types.Issue]
    paras: list[analysis_types._Para]
    field_candidates: list[analysis_types.FieldCandidate]
    section_by_key: dict[str, analysis_types.SectionCandidate]
    combined_body: dict[str, list[analysis_types._Para]]
    by_kind: dict[str, list[analysis_types.SectionCandidate]]
    enabled: EnabledSections

    # -- per-kind prototype mapping ----------------------------------------------------

    def _add_consistency_issue(
        self, proto: list[analysis_types._Para], roles: dict[str, int | None], label: str
    ) -> None:
        consistency_issue = header_fields._prototype_consistency_issue(proto, roles, label)
        if consistency_issue is not None:
            self.issues.append(consistency_issue)

    def _date_issues(
        self,
        field_majority: dict[str, bool],
        field_confidence: dict[str, float],
        date_field: str,
        *,
        missing_code: str,
        partial_code: str,
        noun: str,
        lost: str,
    ) -> None:
        if not field_majority.get(date_field, True):
            self.issues.append(
                analysis_types.Issue(
                    code=missing_code,
                    message=(
                        f"No {noun} entry's header has a detected date. Every "
                        f"rendered {lost} — map the date span "
                        "manually or confirm the header format."
                    ),
                    blocking=True,
                )
            )
        elif field_confidence.get(date_field, 1.0) < 1.0:
            self.issues.append(
                analysis_types.Issue(
                    code=partial_code,
                    message=(
                        f"Only {field_confidence[date_field]:.0%} of {noun} "
                        "entries have a detected date; the rest will render "
                        "without one."
                    ),
                    blocking=False,
                )
            )

    def _map_experience(self) -> ExperienceMapping | None:
        issues = self.issues
        sec = self.section_by_key["experience"]
        body = self.combined_body["experience"]
        entries = entry_structure._split_entries(body)
        if not entries:
            issues.append(
                analysis_types.Issue(
                    code="empty_experience",
                    message="Experience section has no entries to use as a prototype.",
                    blocking=True,
                )
            )
            return None
        # 4d: reconcile field presence across every entry's own header before picking a
        # prototype, so an outlier entry — one that scores well on `_exp_score` (more
        # runs, a title line) but happens to lack a field most other entries have — can
        # never become the prototype and silently lose that field for the whole section.
        candidate_entries, field_majority, field_confidence = (
            header_fields._reconcile_header_fields(
                entries, primary="company", secondary="location", date_field="dates"
            )
        )

        proto = max(candidate_entries, key=field_candidates._exp_score)
        header_para = proto[0]
        header, _hcands = header_fields._entry_header_fields(
            proto, primary="company", secondary="location", date_field="dates"
        )
        self.field_candidates.extend(
            field_candidates._section_field_candidates(
                self.paras,
                self.by_kind["experience"],
                primary="company",
                secondary="location",
                date_field="dates",
                pick=lambda entries: max(entries, key=field_candidates._exp_score),
                include_title=True,
            )
        )
        self._date_issues(
            field_majority, field_confidence, "dates",
            missing_code="experience_dates_not_detected",
            partial_code="experience_dates_partial",
            noun="experience", lost="job would lose its dates",
        )
        proto_main = header_fields._entry_main_paragraphs(proto)
        titles = [x for x in proto_main[1:] if not x.is_bullet and x.text.strip()]
        bullets = [x for x in proto[1:] if x.is_bullet]
        if not bullets:
            # Fall back to any bullet in the section.
            bullets = [x for x in body if x.is_bullet]
        if not bullets:
            issues.append(
                analysis_types.Issue(
                    code="no_experience_bullets",
                    message=(
                        "Experience section has no Word list bullets. "
                        "Entries need real list formatting."
                    ),
                    blocking=True,
                )
            )
            return None
        title_span, title_pid = self._experience_title(titles)
        mapping = ExperienceMapping(
            heading_paragraph_id=sec.heading_paragraph_id,
            heading_text=sec.heading_text,
            prototype_entry_start=header_para.id,
            header=header,
            title=title_span,
            title_paragraph_id=title_pid,
            bullet_paragraph_id=bullets[0].id,
        )
        self._add_consistency_issue(
            proto,
            {"header": header_para.id, "title": title_pid, "bullet": bullets[0].id},
            "Experience",
        )
        return mapping

    def _experience_title(
        self, titles: list[analysis_types._Para]
    ) -> tuple[OptionalSpan, int | None]:
        if titles:
            t = titles[0]
            return OptionalSpan(
                present=True, span=header_fields._span(t.id, 0, len(t.text.strip()))
            ), t.id
        self.issues.append(
            analysis_types.Issue(
                code="inline_title",
                message=(
                    "No separate job-title paragraph found under the experience "
                    "header. Map a title field or ensure each job has a title line."
                ),
                blocking=True,
            )
        )
        return OptionalSpan(present=False), None

    def _map_education(self) -> EducationMapping | None:
        issues = self.issues
        sec = self.section_by_key["education"]
        body = self.combined_body["education"]
        entries = entry_structure._split_entries(body)
        if not entries:
            issues.append(
                analysis_types.Issue(
                    code="empty_education",
                    message="Education heading found but the section has no entries.",
                    blocking=False,
                )
            )
            self.enabled = self.enabled.model_copy(update={"education": False})
            return None
        proto = max(entries, key=field_candidates._edu_score)
        header, _hcands = header_fields._entry_header_fields(
            proto, primary="school", secondary="location", date_field="dates"
        )
        self.field_candidates.extend(
            field_candidates._section_field_candidates(
                self.paras,
                self.by_kind["education"],
                primary="school",
                secondary="location",
                date_field="dates",
                pick=lambda entries: max(entries, key=field_candidates._edu_score),
            )
        )
        bullets, plain_fallback = _education_bullets(proto, body)
        if not bullets:
            issues.append(
                analysis_types.Issue(
                    code="no_education_bullets",
                    message="Education section has no Word list bullets for degree/details.",
                    blocking=True,
                )
            )
            return None
        if plain_fallback:
            issues.append(
                analysis_types.Issue(
                    code="education_bullets_not_list",
                    message=(
                        "Education degree/detail line is not a Word list bullet; "
                        "it will be converted to one in the tagged template."
                    ),
                    blocking=False,
                )
            )
        degree = bullets[0]
        detail = bullets[1] if len(bullets) > 1 else bullets[0]
        mapping = EducationMapping(
            heading_paragraph_id=sec.heading_paragraph_id,
            heading_text=sec.heading_text,
            prototype_entry_start=proto[0].id,
            header=header,
            degree_paragraph_id=degree.id,
            detail_paragraph_id=detail.id,
        )
        self._add_consistency_issue(
            proto,
            {"header": proto[0].id, "degree": degree.id, "detail": detail.id},
            "Education",
        )
        return mapping

    def _map_projects(self) -> ProjectsMapping | None:
        sec = self.section_by_key["projects"]
        body = self.combined_body["projects"]
        entries = entry_structure._split_entries(body)
        if not entries:
            self.enabled = self.enabled.model_copy(update={"projects": False})
            return None
        # 4d: same reconciliation as experience — narrow to the entries agreeing with the
        # section's own modal field-presence signature before applying the existing
        # "prefer fewer runs" tie-break.
        proj_candidate_entries, proj_field_majority, proj_field_confidence = (
            header_fields._reconcile_header_fields(
                entries, primary="name", secondary="tech", date_field="date"
            )
        )
        proto = min(proj_candidate_entries, key=field_candidates._proj_score)

        # Detect the link BEFORE splitting name/tech: its own span (not a fixed word list
        # like "Github"/"Demo"/"Live") comes from the hyperlink itself, so any label
        # works. `exclude_after` then keeps that label out of `tech` — without it, a
        # project with a link but no tech ("Name | Github\tdate") reads the label as tech
        # and the two fields end up with the same span, which the builder rejects as an
        # overlap.
        link, exclude_after, link_cand = field_candidates._detect_project_link(proto)
        if link_cand is not None:
            self.field_candidates.append(link_cand)

        # Cross-cell aware (`_entry_header_fields`, not the plain-text-only
        # `_header_fields_from_text`) so a table-layout Projects section — name/tech in
        # one cell, date in the row's other cell — reconciles and installs identically
        # instead of reconciling fine and then losing the date on the actual installed
        # prototype.
        header, _hcands = header_fields._entry_header_fields(
            proto,
            primary="name",
            secondary="tech",
            date_field="date",
            exclude_after=exclude_after,
        )
        self.field_candidates.extend(
            field_candidates._section_field_candidates(
                self.paras,
                self.by_kind["projects"],
                primary="name",
                secondary="tech",
                date_field="date",
                pick=lambda entries: min(entries, key=field_candidates._proj_score),
                include_link=True,
            )
        )
        self._date_issues(
            proj_field_majority, proj_field_confidence, "date",
            missing_code="project_dates_not_detected",
            partial_code="project_dates_partial",
            noun="project", lost="project would lose its date",
        )
        bullets = [x for x in proto[1:] if x.is_bullet] or [
            x for x in body if x.is_bullet
        ]
        if not bullets:
            self.issues.append(
                analysis_types.Issue(
                    code="no_project_bullets",
                    message="Projects section has no Word list bullets.",
                    blocking=True,
                )
            )
            return None
        mapping = ProjectsMapping(
            heading_paragraph_id=sec.heading_paragraph_id,
            heading_text=sec.heading_text,
            prototype_entry_start=proto[0].id,
            header=header,
            link=link,
            bullet_paragraph_id=bullets[0].id,
        )
        self._add_consistency_issue(
            proto, {"header": proto[0].id, "bullet": bullets[0].id}, "Project"
        )
        return mapping

    def _map_skills(self) -> SkillsMapping | None:
        sec = self.section_by_key["skills"]
        body = [p for p in self.combined_body["skills"] if p.text.strip()]
        if not body:
            self.enabled = self.enabled.model_copy(update={"skills": False})
            return None
        proto = next((p for p in body if ":" in p.text), body[0])
        spans = field_candidates._skills_spans(proto)
        proto_id = proto.id
        if spans is None:
            # Not one paragraph split on a colon — try a table layout's label cell/value
            # cell pairing before giving up.
            cross = field_candidates._skills_pair_across_cells(body)
            if cross is not None:
                spans = cross
                proto_id = cross[0].paragraph_id
        if spans is None:
            self.issues.append(
                analysis_types.Issue(
                    code="skills_format",
                    message=(
                        "Skills lines should look like 'Label: item, item'. "
                        "Could not split the prototype line."
                    ),
                    blocking=True,
                )
            )
            return None
        label_span, body_span, sep = spans
        mapping = SkillsMapping(
            heading_paragraph_id=sec.heading_paragraph_id,
            heading_text=sec.heading_text,
            prototype_paragraph_id=proto_id,
            label_span=label_span,
            body_span=body_span,
            separator=sep,
        )
        self.field_candidates.append(
            analysis_types.FieldCandidate(
                field="skills_label",
                span=label_span,
                confidence=0.9,
                preview=proto.text[label_span.start : label_span.end],
                section_heading_paragraph_id=sec.heading_paragraph_id,
            )
        )
        return mapping

    def _map_list(self) -> ListMapping | None:
        sec = self.section_by_key["list"]
        body = [p for p in self.combined_body["list"] if p.text.strip()]
        bullets = [p for p in body if p.is_bullet]
        if not bullets:
            self.enabled = self.enabled.model_copy(update={"list_section": False})
            return None
        return ListMapping(
            heading_paragraph_id=sec.heading_paragraph_id,
            heading_text=sec.heading_text,
            bullet_paragraph_id=bullets[0].id,
        )


def _education_bullets(
    proto: list[analysis_types._Para], body: list[analysis_types._Para]
) -> tuple[list[analysis_types._Para], bool]:
    """The education prototype's degree + detail paragraphs, and whether they are plain
    (non-list) lines that the build will convert to bullets."""
    proto_main = header_fields._entry_main_paragraphs(proto)
    plain_lines = [x for x in proto_main[1:] if not x.is_bullet and x.text.strip()]
    real_bullets = [x for x in proto[1:] if x.is_bullet] or [
        x for x in body if x.is_bullet
    ]
    plain_fallback = not real_bullets
    if plain_lines and real_bullets:
        # A prose degree line right under the header ("Bachelor of Arts in...", not
        # itself a Word bullet) followed by separately bulleted detail lines (GPA, Dean's
        # List, coursework) — distinct from the shape below, where the degree line IS the
        # first bullet. `edu.degree_line` is a single field, so the prose line is the only
        # sound choice for it; the real bullets become the `edu.details` loop's prototype
        # and, at render time, its actual items.
        return [plain_lines[0]] + real_bullets, plain_fallback
    if plain_fallback:
        # No real Word-list bullets under this entry. `retarget_bullet` (called at build
        # time) creates a paragraph's numbering properties rather than requiring them to
        # already exist, so a plain degree line still produces a working template — it
        # becomes a real bullet in the output. A warning, not a blocker: the visual
        # result is a reasonable, working outcome.
        return [x for x in proto[1:] if x.text.strip()] or [
            x for x in body if x.text.strip()
        ], plain_fallback
    return real_bullets, plain_fallback
