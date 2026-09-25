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
        prefixes = [key[: -len(arg)] for key in self.values if key.endswith(suffix)]
        return [prefix for prefix in prefixes if re.fullmatch(r"[A-Za-z]+-\d+--", prefix)]

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


def test_a_failed_school_search_still_fills_the_rest_of_the_education_row(monkeypatch):
    from resume_tailor.apply.packet import PacketEducation

    written: list[str] = []

    def text_or_prompt(_page, _row, field, value, *, key):
        if key == "school":
            raise TimeoutError("school search timed out")
        written.append(field)
        return True

    monkeypatch.setattr(repeaters, "_section_present", lambda *_a: True)
    monkeypatch.setattr(repeaters, "_rows", lambda *_a: ["education-1--"])
    monkeypatch.setattr(repeaters, "_choose_row", lambda *_a, **_k: "education-1--")
    monkeypatch.setattr(repeaters, "_text_or_prompt", text_or_prompt)
    monkeypatch.setattr(repeaters, "_blank_fill", lambda *_a: True)
    monkeypatch.setattr(repeaters, "_value", lambda *_a: "")
    monkeypatch.setattr(repeaters, "_school_field", lambda *_a: "schoolName")
    monkeypatch.setattr(repeaters, "_ctl", lambda *_a: SimpleNamespace(count=lambda: 1))
    monkeypatch.setattr(repeaters, "_fill_date", lambda _p, _r, field, _v, **_k: written.append(field) or True)
    packet = SimpleNamespace(experience=[], education=[PacketEducation(
        school="University of California - Irvine", major="Computer Science", degree_level="Bachelors",
        start="2023-09", end="2027-06",
    )])
    selected: list[str] = []
    # The page is never touched directly: every row helper is stubbed.
    filled, review = repeaters.fill(
        SimpleNamespace(), packet, lambda _m: None,
        select=lambda _p, _s, value, *, key: selected.append(value) or True,
    )
    assert written == ["fieldOfStudy", "firstYearAttended", "lastYearAttended"]
    assert selected == ["Bachelors"]
    assert filled == []
    assert review == ["Education: University of California - Irvine (School)"]


def test_rows_ignore_error_elements_and_accept_a_school_prompt():
    # Upbound: the school control is `education-N--school` (a prompt), and Workday's
    # `error1-education-N--school` shares the suffix.
    page = _Page({"education-235--school": "", "error1-education-235--school": "", "education-235--fieldOfStudy": ""})
    assert repeaters._rows(page, "schoolName") == []  # noqa: SLF001
    assert repeaters._school_field(page) == "school"  # noqa: SLF001
    assert repeaters._school_field(page, "education-235--") == "school"  # noqa: SLF001


def test_a_committed_school_chip_identifies_its_row():
    page = _Page({"education-1--schoolName": "University of California, Irvine", "education-1--fieldOfStudy": ""})
    row = repeaters._choose_row(  # noqa: SLF001
        page, ["education-1--"], ("University of California - Irvine", "Computer Science"),
        ("schoolName", "fieldOfStudy"),
    )
    assert row == "education-1--"


def _edu(school: str, major: str):
    from resume_tailor.apply.packet import PacketEducation

    return PacketEducation(school=school, major=major, start="2023", end="2027")


def _education_run(monkeypatch, page: _Page, education: list) -> tuple[list[str], list, list[str]]:
    """Run the education step with the search/date helpers stubbed; returns
    (Add clicks, filled, review)."""
    adds: list[str] = []

    def add_row(_page, heading, _anchor):
        adds.append(heading)
        n = 1 + max((int(k.split("-")[1]) for k in page.values if k.startswith("education-")), default=0)
        page.values[f"education-{n}--schoolName"] = ""
        page.values[f"education-{n}--fieldOfStudy"] = ""
        return f"education-{n}--"

    def text_or_prompt(_page, row, field, value, *, key):
        return repeaters._blank_fill(page, row, field, value)  # noqa: SLF001

    monkeypatch.setattr(repeaters, "_add_row", add_row)
    monkeypatch.setattr(repeaters, "_text_or_prompt", text_or_prompt)
    monkeypatch.setattr(repeaters, "_fill_date", lambda *_a, **_k: True)
    packet = SimpleNamespace(experience=[], education=education)
    filled, review = repeaters.fill(page, packet, lambda _m: None)
    return adds, filled, review


def test_continue_reuses_the_education_row_whose_major_the_applicant_changed(monkeypatch):
    # The first pass added the row; the applicant picked another Field of Study, then
    # pressed Continue. The school still identifies the row: no second Education entry.
    page = _Page({"education-1--schoolName": "UC Irvine", "education-1--fieldOfStudy": "Mathematics"})
    adds, filled, review = _education_run(monkeypatch, page, [_edu("UC Irvine", "Computer Science")])
    assert adds == []
    assert review == []
    assert [f["label"] for f in filled] == ["Education: UC Irvine"]
    assert page.values["education-1--fieldOfStudy"] == "Mathematics"


def test_running_the_education_step_twice_leaves_one_row(monkeypatch):
    page = _Page({})
    monkeypatch.setattr(repeaters, "_section_present", lambda *_a: True)
    entries = [_edu("UC Irvine", "Computer Science")]
    first_adds, _, _ = _education_run(monkeypatch, page, entries)
    # A one-result search committed a longer major than the profile's.
    page.values["education-1--fieldOfStudy"] = "Computer and Information Science"
    second_adds, _, review = _education_run(monkeypatch, page, entries)
    assert (first_adds, second_adds) == (["Education"], [])
    assert review == []
    assert sorted(k for k in page.values if k.endswith("--schoolName")) == ["education-1--schoolName"]


def test_two_entries_at_one_school_do_not_reuse_by_school_alone(monkeypatch):
    # One row at the school with an unrelated major: which entry it belongs to is
    # unknowable, so the first entry does not claim it; one row short means one add.
    page = _Page({"education-1--schoolName": "UC Irvine", "education-1--fieldOfStudy": "Mathematics"})
    adds, _, _ = _education_run(
        monkeypatch, page, [_edu("UC Irvine", "Computer Science"), _edu("UC Irvine", "Physics")],
    )
    assert adds == ["Education"]


def test_rows_already_covering_every_entry_block_the_add(monkeypatch):
    page = _Page({
        "education-1--schoolName": "UC Irvine", "education-1--fieldOfStudy": "Mathematics",
        "education-2--schoolName": "UC Irvine", "education-2--fieldOfStudy": "History",
    })
    adds, _, review = _education_run(
        monkeypatch, page, [_edu("UC Irvine", "Computer Science"), _edu("UC Irvine", "Physics")],
    )
    assert adds == []
    assert all("possible duplicate row" in item for item in review) and len(review) == 2


def test_a_major_match_is_tried_both_ways():
    assert repeaters._same("computer and information science", "computer science", "major")  # noqa: SLF001
    assert repeaters._same("computer science", "computer and information science", "major")  # noqa: SLF001
    assert not repeaters._same("stanford university", "uc irvine", "school")  # noqa: SLF001


def test_a_row_rendered_after_the_wait_is_still_returned(monkeypatch):
    class _SlowPage(_Page):
        waits = 0

        def evaluate(self, script, arg):
            if script == repeaters._ADD_BUTTON_JS:  # noqa: SLF001
                return 0
            return super().evaluate(script, arg)

        def wait_for_timeout(self, ms):
            self.waits += 1
            if ms == 1500:  # the late look: the row has rendered by now
                self.values["education-2--schoolName"] = ""

    page = _SlowPage({"education-1--schoolName": "UC Irvine"})
    monkeypatch.setattr(repeaters.clicks, "safe_click", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "locator", lambda _s: SimpleNamespace(nth=lambda _i: None), raising=False)
    assert repeaters._add_row(page, "Education", "schoolName") == "education-2--"  # noqa: SLF001
