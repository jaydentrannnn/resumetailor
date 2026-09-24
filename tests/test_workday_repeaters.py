"""Workday repeater identity and preservation rules without a live browser.

Row controls use the live id scheme ``workExperience-<n>--<field>`` / ``education-<n>--<field>``.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from resume_tailor.apply import workday_repeaters as repeaters


class _Control:
    def __init__(self, page: _Page, control_id: str) -> None:
        self.page = page
        self.id = control_id

    @property
    def first(self) -> _Control:
        return self

    def count(self) -> int:
        return int(self.id in self.page.values)

    def input_value(self) -> str:
        return self.page.values.get(self.id, "")

    def get_attribute(self, _name: str) -> None:
        return None

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def click(self, timeout: int | None = None) -> None:
        # Clicking a date section's display div focuses its hidden input.
        self.page.focused = self.id.replace("-display", "-input")

    def fill(self, value: str, timeout: int | None = None) -> None:
        self.page.values[self.id] = value
        self.page.writes.append(self.id)


class _Keyboard:
    def __init__(self, page: _Page) -> None:
        self.page = page

    def type(self, text: str, delay: int = 0) -> None:
        self.page.values[self.page.focused] = text
        self.page.writes.append(self.page.focused)


class _Page:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = dict(values)
        self.writes: list[str] = []
        self.focused = ""
        self.keyboard = _Keyboard(self)

    def locator(self, selector: str) -> _Control:
        match = re.fullmatch(r"\[id='([^']+)'\]", selector)
        assert match, selector
        return _Control(self, match.group(1))

    def evaluate(self, script: str, arg: str) -> list[str] | None:
        if script == repeaters._CHIPS_JS:  # noqa: SLF001 - no prompt fields in these rows
            return None
        if script == repeaters._ADD_BUTTON_JS:  # noqa: SLF001 - no section Add buttons here
            return -1
        assert script == repeaters._ROWS_JS  # noqa: SLF001
        suffix = f"--{arg}"
        return [key[: -len(arg)] for key in self.values if key.endswith(suffix)]

    def wait_for_timeout(self, _ms: int) -> None:
        pass


def _work_rows(*rows: tuple[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for index, (title, company) in enumerate(rows, start=1):
        values[f"workExperience-{index}--jobTitle"] = title
        values[f"workExperience-{index}--companyName"] = company
    return values


def test_same_title_at_different_companies_stays_distinct():
    page = _Page(_work_rows(("Analyst", "Company A"), ("Analyst", "Company B")))
    rows = repeaters._rows(page, "jobTitle")  # noqa: SLF001
    chosen = repeaters._choose_row(page, rows, ("Analyst", "Company B"), ("jobTitle", "companyName"))  # noqa: SLF001
    assert chosen == "workExperience-2--"


def test_two_degrees_at_one_school_stay_distinct():
    page = _Page({
        "education-1--schoolName": "UC Irvine", "education-1--fieldOfStudy": "Physics",
        "education-2--schoolName": "UC Irvine", "education-2--fieldOfStudy": "Computer Science",
    })
    rows = repeaters._rows(page, "schoolName")  # noqa: SLF001
    chosen = repeaters._choose_row(  # noqa: SLF001
        page, rows, ("UC Irvine", "Computer Science"), ("schoolName", "fieldOfStudy"),
    )
    assert chosen == "education-2--"


def test_only_a_single_blank_row_is_reused():
    page = _Page(_work_rows(("", ""), ("", "")))
    rows = repeaters._rows(page, "jobTitle")  # noqa: SLF001
    assert repeaters._choose_row(page, rows, ("Analyst", "Acme"), ("jobTitle", "companyName")) is None  # noqa: SLF001


def test_existing_answers_are_never_replaced():
    page = _Page({"workExperience-1--jobTitle": "User's own answer"})
    assert not repeaters._blank_fill(page, "workExperience-1--", "jobTitle", "Prepared answer")  # noqa: SLF001
    assert page.writes == []
    assert repeaters._blank_fill(page, "workExperience-1--", "jobTitle", "user's own answer")  # noqa: SLF001


def test_split_date_types_month_and_year_and_keeps_existing():
    prefix = "workExperience-1--"
    page = _Page({
        f"{prefix}startDate-dateSectionMonth-input": "",
        f"{prefix}startDate-dateSectionYear-input": "",
        f"{prefix}endDate-dateSectionMonth-input": "03",
        f"{prefix}endDate-dateSectionYear-input": "2024",
    })
    assert repeaters._fill_date(page, prefix, "startDate", "2025-01", with_month=True)  # noqa: SLF001
    assert page.values[f"{prefix}startDate-dateSectionMonth-input"] == "01"
    assert page.values[f"{prefix}startDate-dateSectionYear-input"] == "2025"
    # A different existing end date is the applicant's; it is kept and flagged.
    assert not repeaters._fill_date(page, prefix, "endDate", "2025-06", with_month=True)  # noqa: SLF001
    assert page.values[f"{prefix}endDate-dateSectionYear-input"] == "2024"


def test_a_row_started_by_an_earlier_run_is_completed_not_duplicated():
    page = _Page({
        "education-1--schoolName": "UC Irvine", "education-1--fieldOfStudy": "",
        "education-2--schoolName": "", "education-2--fieldOfStudy": "",
    })
    rows = repeaters._rows(page, "schoolName")  # noqa: SLF001
    chosen = repeaters._choose_row(  # noqa: SLF001
        page, rows, ("UC Irvine", "Computer Science"), ("schoolName", "fieldOfStudy"),
    )
    assert chosen == "education-1--"
    # A partial row that disagrees on a filled field is someone else's.
    page.values["education-1--schoolName"] = "Stanford"
    assert repeaters._choose_row(  # noqa: SLF001
        page, rows, ("UC Irvine", "Computer Science"), ("schoolName", "fieldOfStudy"),
    ) == "education-2--"


def test_a_step_without_experience_sections_flags_nothing():
    # Capital Group's My Experience asks only for Skills and a resume.
    page = _Page({})
    packet = SimpleNamespace(
        experience=[SimpleNamespace(title="Analyst", employer="Acme")],
        education=[SimpleNamespace(school="UC Irvine", major="CS")],
    )
    messages: list[str] = []
    filled, review = repeaters.fill(page, packet, messages.append)
    assert (filled, review) == ([], [])
    assert any("no Work Experience section" in m for m in messages)
    assert page.writes == []
