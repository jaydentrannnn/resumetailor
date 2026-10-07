"""Conservative, row-scoped filling of Workday employment, education and language lists.

Current Workday renders each row's controls with ids ``workExperience-<n>--<field>`` /
``education-<n>--<field>`` (captured live 2026-09), and a per-section "Add" / "Add
Another" button under the section heading. A row is reused only when its identity fields
match exactly, or when it is the single blank row; otherwise a row is added. Existing
answers are never replaced, and anything that cannot be verified is reported for review.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import field_matcher
from resume_tailor.apply.funnel.packet_models import Packet

from . import workday_dates, workday_rows


def _tick(page: Any, prefix: str, field: str) -> bool:
    box = workday_rows._ctl(page, prefix, field)
    if box.count() == 1 and not box.first.is_checked():
        try:
            box.first.check(timeout=2000)
        except Exception:  # noqa: BLE001 - styled checkbox: its label takes the click
            clicks.safe_click(page.locator(f"label[for='{prefix}{field}']").first, purpose="select", timeout=3000)
    return box.count() == 1 and box.first.is_checked()


def _tick_current(page: Any, prefix: str) -> bool:
    return _tick(page, prefix, workday_rows._WORK["current"])


def _choose(page: Any, prefix: str, field: str, value: str, *, key: str, select: Callable[..., bool] | None) -> bool:
    """A listbox button or a prompt; an existing answer is kept (ok only if it means ``value``)."""
    current = workday_rows._value(page, prefix, field)
    if current:
        return current.casefold() == value.casefold() or bool(field_matcher.closest_option([current], value, key=key))
    control = workday_rows._ctl(page, prefix, field)
    if control.count() == 1 and control.first.get_attribute("aria-haspopup") == "listbox":
        return bool(select and select(page, f"[id='{prefix}{field}']", value, key=key))
    return workday_dates._text_or_prompt(page, prefix, field, value, key=key)


def _fill_language(page: Any, row: str, entry: Any, select: Callable[..., bool] | None) -> dict[str, bool]:
    """Language, the fluent checkbox, and one level per proficiency control of one row.

    Levels are matched by the control's label ("Reading", "Speaking", ...); a lone
    unlabelled level control takes the "Overall" level. A level the profile does not give
    is a gap for the applicant, not a guess.
    """
    from resume_tailor.apply.answers.profile import LANGUAGE_CATEGORIES  # noqa: PLC0415

    results = {
        "Language": workday_rows._attempt(
            lambda: _choose(
                page, row, workday_rows._LANGUAGE, entry.language, key="language", select=select
            )
        )
    }
    try:
        controls = page.evaluate(workday_rows._ROW_CONTROLS_JS, row) or []
    except Exception:  # noqa: BLE001
        controls = []
    for control in controls:
        field = str(control["id"])[len(row):]
        if control.get("checkbox"):
            if re.search(r"fluent|native", str(control.get("label") or ""), re.I) and entry.fluent:
                results["Fluent"] = workday_rows._attempt(lambda f=field: _tick(page, row, f))
            continue
        if not control.get("listbox") or field == workday_rows._LANGUAGE:
            continue
        label = str(control.get("label") or "")
        category = next((name for name in LANGUAGE_CATEGORIES if name.casefold() in label.casefold()), "Overall")
        level = entry.levels.get(category, "")
        if workday_rows._value(page, row, field):
            continue
        name = label or category
        results[name] = bool(level) and workday_rows._attempt(
            lambda f=field, v=level: bool(select and select(page, f"[id='{row}{f}']", v, key="language_level")),
        )
    return results


def _reuse_or_guard(
    page: Any, rows: list[str], anchors: list[str], field: str, claimed: set[str]
) -> tuple[str | None, bool]:
    """When no row matches an entry's full identity: (row to reuse, add is blocked).

    ``anchors`` is this entry's school/employer followed by the remaining entries'. The
    single unclaimed row holding it is reused when no later entry shares the value. When
    the page already holds at least as many such rows as the entries still to place,
    adding one would duplicate an existing row, so the add is blocked for review.
    """
    wanted = anchors[0]
    if not wanted:
        return None, False
    matching = workday_rows._anchor_rows(page, rows, wanted, field, exclude=claimed)
    key = workday_rows._MATCH_KEYS.get(field, "")
    still_to_place = sum(
        1
        for other in anchors
        if workday_rows._same(other.strip().casefold(), wanted.strip().casefold(), key)
    )
    if len(matching) == 1 and still_to_place == 1:
        return matching[0], False
    return None, len(matching) >= still_to_place


def fill(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None],
    *,
    select: Callable[..., bool] | None = None,
    dismiss: Callable[[Any], Any] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Populate prepared entries where an exact or blank row is observable.

    Returns (filled, needs_review): filled rows as ``{"label", "value"}`` records and the
    human labels of rows or fields left for the applicant. ``dismiss`` closes a popup an
    earlier pass left open (`workday_page.close_stray_popups`); it runs before the rows
    and again when an Add press is blocked.
    """
    filled: list[dict[str, str]] = []
    review: list[str] = []
    # This runs on every Workday step: a narrow window hides the step names that once
    # limited it to My Experience (2026-10). A step showing none of these sections is
    # left alone, silently.
    if not any(
        workday_rows._section_present(page, heading, anchor)
        for heading, anchor in (
            ("Work Experience", workday_rows._WORK["title"]),
            ("Education", workday_dates._school_field(page)),
            ("Languages", workday_rows._LANGUAGE),
        )
    ):
        return filled, review
    if dismiss is not None:
        dismiss(page)
    #: Section heading -> why its Add button could not be pressed; later entries in the
    #: section are flagged with the same reason instead of waiting on the same failure.
    blocked_add: dict[str, str] = {}

    def add(heading: str, anchor: str | tuple[str, ...]) -> str | None:
        if heading in blocked_add:
            raise workday_rows.AddRowError(blocked_add[heading])
        try:
            row = workday_rows._add_row(page, heading, anchor, dismiss=dismiss)
            if row is None:
                # AmerisourceBergen (2026-10): two employment rows were dropped when the
                # press showed no single new row. Recover instead of skipping the entry.
                row = workday_rows._recover_row(
                    page,
                    anchor,
                    claimed,
                    lambda: workday_rows._add_row(page, heading, anchor, dismiss=dismiss),
                    dismiss=dismiss,
                )
                progress(f"Workday: {heading} Add showed no new row; "
                         + (f"recovered row {row}" if row else "no row after a second press"))
            return row
        except workday_rows.AddRowError as exc:
            blocked_add[heading] = str(exc)
            raise

    def why(exc: BaseException) -> str:
        return str(exc) if isinstance(exc, workday_rows.AddRowError) else workday_rows._reason(exc)

    # Some tenants (Capital Group, 2026-09) ask only for a resume on My Experience; a
    # section that is not on the page is not a gap to review.
    experience = packet.experience
    if experience and not workday_rows._section_present(
        page, "Work Experience", workday_rows._WORK["title"]
    ):
        progress("This Workday step has no Work Experience section; skipping employment rows")
        experience = []
    if experience:
        progress("Inspecting Workday employment rows")
    claimed: set[str] = set()
    #: Filled rows and their dates, re-checked once every row is placed.
    placed: list[tuple[str, str, list[tuple[str, str, bool]]]] = []
    for index, exp in enumerate(experience):
        label = f"Work experience: {exp.title} at {exp.employer}"
        try:
            rows = workday_rows._rows(page, workday_rows._WORK["title"])
            row = workday_rows._choose_row(
                page,
                rows,
                (exp.title, exp.employer),
                (workday_rows._WORK["title"], workday_rows._WORK["company"]),
                exclude=claimed,
            )
            if row is None:
                row, blocked = _reuse_or_guard(
                    page,
                    rows,
                    [e.employer for e in experience[index:]],
                    workday_rows._WORK["company"],
                    claimed,
                )
                if blocked:
                    progress(f"Workday: {label} already has a row; not adding another")
                    review.append(f"{label} (possible duplicate row: check the list)")
                    continue
            if row is None:
                row = add("Work Experience", workday_rows._WORK["title"])
            if row is None:
                review.append(label)
                continue
            claimed.add(row)
            results = {
                "Job Title": workday_rows._attempt(
                    lambda: workday_dates._blank_fill(
                        page, row, workday_rows._WORK["title"], exp.title
                    )
                ),
                "Company": workday_rows._attempt(
                    lambda: workday_dates._blank_fill(
                        page, row, workday_rows._WORK["company"], exp.employer
                    )
                ),
                "Location": workday_rows._attempt(
                    lambda: workday_dates._blank_fill(
                        page, row, workday_rows._WORK["location"], exp.location
                    )
                ),
                "Role Description": workday_rows._attempt(
                    lambda: workday_dates._blank_fill(
                        page, row, workday_rows._WORK["description"], exp.description
                    )
                ),
            }
            if exp.current:
                results["I currently work here"] = workday_rows._attempt(
                    lambda: _tick_current(page, row)
                )
            results["From"] = workday_dates._fill_date_retrying(
                page, row, "startDate", exp.start, with_month=True, note=progress
            )
            if not exp.current:
                results["To"] = workday_dates._fill_date_retrying(
                    page, row, "endDate", exp.end, with_month=True, note=progress
                )
            failed = [name for name, ok in results.items() if not ok]
            if not failed:
                progress(f"Workday: filled {label}")
                filled.append({"label": label, "value": f"{exp.start} - {exp.end or 'present'}"})
                placed.append((row, label, [("startDate", exp.start, True)]
                               + ([] if exp.current else [("endDate", exp.end, True)])))
            else:
                review.append(f"{label} ({', '.join(failed)})")
        except Exception as exc:  # noqa: BLE001 - preserve the rest of the batch
            progress(f"Workday employment row needs review: {exp.title} at {exp.employer} ({why(exc)})")
            review.append(f"{label} ({why(exc)})")

    workday_dates._recheck_dates(page, placed, filled, review, progress)

    education = packet.education
    school = workday_dates._school_field(page)
    if education and not workday_rows._section_present(page, "Education", school):
        progress("This Workday step has no Education section; skipping education rows")
        education = []
    if education:
        progress("Inspecting Workday education rows")
    claimed = set()
    for index, edu in enumerate(education):
        label = f"Education: {edu.school}"
        try:
            rows = workday_rows._rows(page, school)
            row = workday_rows._choose_row(
                page,
                rows,
                (edu.school, edu.major),
                (school, workday_rows._EDU["major"]),
                exclude=claimed,
            )
            reused_by_school = False
            if row is None:
                # Continue / Reopen / error recovery re-run this step: the row this fill
                # added earlier may now carry a Field of Study the applicant picked or
                # fixed. Its school still identifies it; adding a row would duplicate it.
                row, blocked = _reuse_or_guard(
                    page, rows, [e.school for e in education[index:]], school, claimed,
                )
                reused_by_school = row is not None
                if blocked:
                    progress(f"Workday: {label} already has a row; not adding another")
                    review.append(f"{label} (possible duplicate row: check the list)")
                    continue
            if row is None:
                row = add("Education", workday_rows._SCHOOL_FIELDS)
            if row is None:
                progress(f"Workday: no education row available for {edu.school}")
                review.append(label)
                continue
            claimed.add(row)
            school = workday_dates._school_field(page, row)
            current_major = workday_rows._value(page, row, workday_rows._EDU["major"])
            kept_major = current_major if reused_by_school or workday_rows._same(
                current_major.casefold(), edu.major.strip().casefold(), "major"
            ) else ""
            # Each field on its own: a school search that fails (Upbound, 2026-09) must
            # not leave the major, years, and degree unfilled.
            results = {
                "School": workday_rows._attempt(
                    lambda: workday_dates._text_or_prompt(
                        page, row, school, edu.school, key="school"
                    )
                ),
                # A Field of Study already there that matches (or, on a row found by its
                # school, any one: the applicant's reviewed answer) is kept, not flagged
                # again on every Continue.
                "Field of Study": bool(kept_major)
                or workday_rows._attempt(
                    lambda: workday_dates._text_or_prompt(
                        page, row, workday_rows._EDU["major"], edu.major, key="major"
                    )
                ),
                # Most tenants do not ask for a GPA; an absent control is not a gap.
                "GPA": workday_rows._attempt(
                    lambda: (
                        workday_rows._ctl(page, row, workday_rows._EDU["gpa"]).count() == 0
                        or workday_dates._blank_fill(page, row, workday_rows._EDU["gpa"], edu.gpa)
                    )
                ),
                # Years attended are optional per tenant (F5 asks none): absent is not a gap.
                "From": workday_rows._attempt(
                    lambda: (
                        workday_dates._date_absent(page, row, "firstYearAttended")
                        or workday_dates._fill_date_retrying(
                            page,
                            row,
                            "firstYearAttended",
                            edu.start,
                            with_month=False,
                            note=progress,
                        )
                    )
                ),
                "To": workday_rows._attempt(
                    lambda: (
                        workday_dates._date_absent(page, row, "lastYearAttended")
                        or workday_dates._fill_date_retrying(
                            page, row, "lastYearAttended", edu.end, with_month=False, note=progress
                        )
                    )
                ),
            }
            degree = edu.degree_name or edu.degree_level or edu.degree
            if degree and not workday_rows._value(page, row, workday_rows._EDU["degree"]):
                # Most specific first: "Bachelor of Science in X" -> "Bachelor of Science" -> "Bachelors".
                candidates = [edu.degree_name, re.sub(r"\s+in\s+.*$", "", edu.degree_name or ""),
                              edu.degree_level, edu.degree]
                chosen = False
                for candidate in dict.fromkeys(c for c in candidates if c):
                    if select and workday_rows._attempt(
                        lambda c=candidate: select(
                            page,
                            f"[id='{row}{workday_rows._EDU['degree']}']",
                            c,
                            key="degree_level",
                        )
                    ):
                        chosen = True
                        break
                results["Degree"] = chosen
            failed = [name for name, ok in results.items() if not ok]
            if not failed:
                progress(f"Workday: filled {label}")
                filled.append({"label": label, "value": degree})
            else:
                progress(f"Workday: {label} needs review ({', '.join(failed)})")
                review.append(f"{label} ({', '.join(failed)})")
        except Exception as exc:  # noqa: BLE001
            progress(f"Workday education row needs review: {edu.school} ({why(exc)})")
            review.append(f"{label} ({why(exc)})")

    languages = getattr(packet, "languages", [])
    if languages and not workday_rows._section_present(page, "Languages", workday_rows._LANGUAGE):
        languages = []
    if languages:
        progress("Inspecting Workday language rows")
    for entry in languages:
        label = f"Language: {entry.language}"
        try:
            row = workday_rows._choose_row(
                page,
                workday_rows._rows(page, workday_rows._LANGUAGE),
                (entry.language,),
                (workday_rows._LANGUAGE,),
            )
            if row is None:
                row = add("Languages", workday_rows._LANGUAGE)
            if row is None:
                progress(f"Workday: no language row available for {entry.language}")
                review.append(label)
                continue
            results = _fill_language(page, row, entry, select)
            failed = [name for name, ok in results.items() if not ok]
            if not failed:
                progress(f"Workday: filled {label}")
                filled.append({"label": label, "value": entry.language})
            else:
                progress(f"Workday: {label} needs review ({', '.join(failed)})")
                review.append(f"{label} ({', '.join(failed)})")
        except Exception as exc:  # noqa: BLE001
            progress(f"Workday language row needs review: {entry.language} ({why(exc)})")
            review.append(f"{label} ({why(exc)})")
    return filled, review


async def fill_education_years_async(page: Any, packet: Packet) -> tuple[list[dict[str, str]], list[str]]:
    """Fill split Workday education year controls in the verified engine.

    The ordinary scanner handles visible inputs and selectors. This covers Workday's
    zero-width year spinbuttons, which the scanner intentionally cannot observe.
    """
    rows = await page.evaluate(r"""() => [...document.querySelectorAll('[id$="--schoolName"]')]
      .map(el => ({prefix: el.id.slice(0, -'schoolName'.length), school: el.value || '',
        major: document.getElementById(el.id.replace('schoolName', 'fieldOfStudy'))?.value || ''}))""")
    filled: list[dict[str, str]] = []
    review: list[str] = []
    for row in rows or []:
        matches = [edu for edu in packet.education if edu.school.strip().casefold() == str(row["school"]).strip().casefold()
                   and (not row["major"] or edu.major.strip().casefold() == str(row["major"]).strip().casefold())]
        if len(matches) != 1:
            continue
        edu = matches[0]
        for field, date in (("firstYearAttended", edu.start), ("lastYearAttended", edu.end)):
            _month, year = workday_dates._date_parts(date)
            if not year:
                continue
            prefix = str(row["prefix"])
            year_input = page.locator(f"[id='{prefix}{field}-dateSectionYear-input']")
            if await year_input.count() != 1:
                continue  # ordinary visible controls belong to the scanner
            current = str(await year_input.input_value() or "").strip()
            label = f"Education: {edu.school} {field}"
            if current and current != year:
                review.append(label)
                continue
            if not current:
                display = page.locator(f"[id='{prefix}{field}-dateSectionYear-display']")
                if await display.count() != 1:
                    review.append(label)
                    continue
                await clicks.async_safe_click(display, purpose="select", timeout=3000)
                await page.keyboard.type(year, delay=40)
                await page.keyboard.press("Tab")
            if str(await year_input.input_value() or "").strip() == year:
                filled.append({"label": label, "value": year})
            else:
                review.append(label)
    return filled, review
