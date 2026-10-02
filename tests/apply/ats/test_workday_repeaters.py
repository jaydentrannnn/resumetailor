"""Workday repeater identity and preservation rules without a live browser.

Row controls use the live id scheme ``workExperience-<n>--<field>`` / ``education-<n>--<field>``.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from resume_tailor.apply.ats import workday_dates, workday_rows
from resume_tailor.apply.ats import workday_repeaters as repeaters


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

    def focus(self) -> None:
        self.page.focused = self.id


class _Keyboard:
    def __init__(self, page: _Page) -> None:
        self.page = page

    def type(self, text: str, delay: int = 0) -> None:
        self.page.typed.append(text)
        if self.page.drop_typing:  # the keys land nowhere (focus was elsewhere)
            self.page.drop_typing -= 1
            return
        self.page.values[self.page.focused] = text
        self.page.writes.append(self.page.focused)

    def press(self, key: str) -> None:
        self.page.pressed.append(key)
        if key == "Backspace":  # after select-all: empties the focused input
            self.page.values[self.page.focused] = ""


class _Page:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = dict(values)
        self.writes: list[str] = []
        self.focused = ""
        self.typed: list[str] = []
        self.pressed: list[str] = []
        self.drop_typing = 0  # how many `keyboard.type` calls to lose
        self.keyboard = _Keyboard(self)

    def locator(self, selector: str) -> _Control:
        prefix = re.fullmatch(r"\[id\^='([^']+)'\]", selector)
        if prefix:  # controls whose id starts with the text (split date sections)
            return SimpleNamespace(count=lambda: sum(key.startswith(prefix.group(1)) for key in self.values))
        match = re.fullmatch(r"\[id='([^']+)'\]", selector)
        assert match, selector
        return _Control(self, match.group(1))

    def evaluate(self, script: str, arg: str) -> list[str] | None:
        if script == workday_rows._CHIPS_JS:  # noqa: SLF001 - no prompt fields in these rows
            return None
        if script == workday_rows._ADD_BUTTON_JS:  # noqa: SLF001 - no section Add buttons here
            return -1
        assert script == workday_rows._ROWS_JS  # noqa: SLF001
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
    rows = workday_rows._rows(page, "jobTitle")  # noqa: SLF001
    chosen = workday_rows._choose_row(
        page, rows, ("Analyst", "Company B"), ("jobTitle", "companyName")
    )  # noqa: SLF001
    assert chosen == "workExperience-2--"


def test_two_degrees_at_one_school_stay_distinct():
    page = _Page({
        "education-1--schoolName": "UC Irvine", "education-1--fieldOfStudy": "Physics",
        "education-2--schoolName": "UC Irvine", "education-2--fieldOfStudy": "Computer Science",
    })
    rows = workday_rows._rows(page, "schoolName")  # noqa: SLF001
    chosen = workday_rows._choose_row(  # noqa: SLF001
        page, rows, ("UC Irvine", "Computer Science"), ("schoolName", "fieldOfStudy"),
    )
    assert chosen == "education-2--"


def test_only_a_single_blank_row_is_reused():
    page = _Page(_work_rows(("", ""), ("", "")))
    rows = workday_rows._rows(page, "jobTitle")  # noqa: SLF001
    assert (
        workday_rows._choose_row(page, rows, ("Analyst", "Acme"), ("jobTitle", "companyName"))
        is None
    )  # noqa: SLF001


def test_existing_answers_are_never_replaced():
    page = _Page({"workExperience-1--jobTitle": "User's own answer"})
    assert not workday_dates._blank_fill(page, "workExperience-1--", "jobTitle", "Prepared answer")  # noqa: SLF001
    assert page.writes == []
    assert workday_dates._blank_fill(page, "workExperience-1--", "jobTitle", "user's own answer")  # noqa: SLF001


def test_split_date_types_month_and_year_and_keeps_existing():
    prefix = "workExperience-1--"
    page = _Page({
        f"{prefix}startDate-dateSectionMonth-input": "",
        f"{prefix}startDate-dateSectionYear-input": "",
        f"{prefix}endDate-dateSectionMonth-input": "03",
        f"{prefix}endDate-dateSectionYear-input": "2024",
    })
    assert workday_dates._fill_date(page, prefix, "startDate", "2025-01", with_month=True)  # noqa: SLF001
    assert page.values[f"{prefix}startDate-dateSectionMonth-input"] == "01"
    assert page.values[f"{prefix}startDate-dateSectionYear-input"] == "2025"
    # A different existing end date is the applicant's; it is kept and flagged.
    assert not workday_dates._fill_date(page, prefix, "endDate", "2025-06", with_month=True)  # noqa: SLF001
    assert page.values[f"{prefix}endDate-dateSectionYear-input"] == "2024"


_START = "workExperience-1--startDate-dateSection"


def _start_page(month: str = "", year: str = "") -> _Page:
    return _Page({f"{_START}Month-input": month, f"{_START}Year-input": year})


def test_a_date_typed_into_nothing_is_typed_again():
    # CACI (2026-09): the keys went to whatever held focus and the section stayed empty.
    page = _start_page()
    page.drop_typing = 1
    assert workday_dates._fill_date(
        page, "workExperience-1--", "startDate", "2025-01", with_month=True
    )  # noqa: SLF001
    assert page.values[f"{_START}Month-input"] == "01"
    assert page.values[f"{_START}Year-input"] == "2025"
    assert page.typed == ["01", "01", "2025"]  # the month twice, the year once
    assert "Backspace" in page.pressed  # the retry clears the section before typing


def test_a_date_that_never_lands_is_reported_not_claimed():
    page = _start_page()
    page.drop_typing = 2  # both attempts at the month are lost
    assert not workday_dates._fill_date(
        page, "workExperience-1--", "startDate", "2025-01", with_month=True
    )  # noqa: SLF001
    assert page.values[f"{_START}Month-input"] == ""
    assert page.typed.count("01") == 2  # retried once, not forever


def test_a_partial_month_is_retyped_not_taken_for_the_applicants_own_date():
    page = _start_page(month="0")  # one keystroke of "03" landed
    assert workday_dates._fill_date(
        page, "workExperience-1--", "startDate", "2025-03", with_month=True
    )  # noqa: SLF001
    assert page.values[f"{_START}Month-input"] == "03"
    assert page.values[f"{_START}Year-input"] == "2025"
    assert "Backspace" in page.pressed  # the stray "0" is cleared first


def test_an_existing_matching_date_is_not_typed_again():
    page = _start_page(month="03", year="2025")
    assert workday_dates._fill_date(
        page, "workExperience-1--", "startDate", "2025-03", with_month=True
    )  # noqa: SLF001
    assert page.typed == [] and page.pressed == []


def test_an_existing_different_date_is_kept_even_when_it_looks_partial():
    page = _start_page(month="1", year="2024")  # "1" is not the start of "03"
    assert not workday_dates._fill_date(
        page, "workExperience-1--", "startDate", "2025-03", with_month=True
    )  # noqa: SLF001
    assert page.values[f"{_START}Month-input"] == "1"
    assert page.values[f"{_START}Year-input"] == "2024"
    assert page.typed == []


def test_a_row_started_by_an_earlier_run_is_completed_not_duplicated():
    page = _Page({
        "education-1--schoolName": "UC Irvine", "education-1--fieldOfStudy": "",
        "education-2--schoolName": "", "education-2--fieldOfStudy": "",
    })
    rows = workday_rows._rows(page, "schoolName")  # noqa: SLF001
    chosen = workday_rows._choose_row(  # noqa: SLF001
        page, rows, ("UC Irvine", "Computer Science"), ("schoolName", "fieldOfStudy"),
    )
    assert chosen == "education-1--"
    # A partial row that disagrees on a filled field is someone else's.
    page.values["education-1--schoolName"] = "Stanford"
    assert workday_rows._choose_row(  # noqa: SLF001
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
    from resume_tailor.apply.funnel.packet_models import PacketEducation

    written: list[str] = []

    def text_or_prompt(_page, _row, field, value, *, key):
        if key == "school":
            raise TimeoutError("school search timed out")
        written.append(field)
        return True

    monkeypatch.setattr(workday_rows, "_section_present", lambda *_a: True)
    monkeypatch.setattr(workday_rows, "_rows", lambda *_a: ["education-1--"])
    monkeypatch.setattr(workday_rows, "_choose_row", lambda *_a, **_k: "education-1--")
    monkeypatch.setattr(workday_dates, "_text_or_prompt", text_or_prompt)
    monkeypatch.setattr(workday_dates, "_blank_fill", lambda *_a: True)
    monkeypatch.setattr(workday_rows, "_value", lambda *_a: "")
    monkeypatch.setattr(workday_dates, "_school_field", lambda *_a: "schoolName")
    monkeypatch.setattr(workday_rows, "_ctl", lambda *_a: SimpleNamespace(count=lambda: 1))
    monkeypatch.setattr(
        workday_dates, "_fill_date", lambda _p, _r, field, _v, **_k: written.append(field) or True
    )
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
    assert workday_rows._rows(page, "schoolName") == []  # noqa: SLF001
    assert workday_dates._school_field(page) == "school"  # noqa: SLF001
    assert workday_dates._school_field(page, "education-235--") == "school"  # noqa: SLF001


def test_a_committed_school_chip_identifies_its_row():
    page = _Page({"education-1--schoolName": "University of California, Irvine", "education-1--fieldOfStudy": ""})
    row = workday_rows._choose_row(  # noqa: SLF001
        page, ["education-1--"], ("University of California - Irvine", "Computer Science"),
        ("schoolName", "fieldOfStudy"),
    )
    assert row == "education-1--"


def _edu(school: str, major: str):
    from resume_tailor.apply.funnel.packet_models import PacketEducation

    return PacketEducation(school=school, major=major, start="2023", end="2027")


def _education_run(monkeypatch, page: _Page, education: list) -> tuple[list[str], list, list[str]]:
    """Run the education step with the search/date helpers stubbed; returns
    (Add clicks, filled, review)."""
    adds: list[str] = []

    def add_row(_page, heading, _anchor, **_kw):
        adds.append(heading)
        n = 1 + max((int(k.split("-")[1]) for k in page.values if k.startswith("education-")), default=0)
        page.values[f"education-{n}--schoolName"] = ""
        page.values[f"education-{n}--fieldOfStudy"] = ""
        return f"education-{n}--"

    def text_or_prompt(_page, row, field, value, *, key):
        return workday_dates._blank_fill(page, row, field, value)  # noqa: SLF001

    monkeypatch.setattr(workday_rows, "_add_row", add_row)
    monkeypatch.setattr(workday_dates, "_text_or_prompt", text_or_prompt)
    monkeypatch.setattr(workday_dates, "_fill_date", lambda *_a, **_k: True)
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
    monkeypatch.setattr(workday_rows, "_section_present", lambda *_a: True)
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
    assert workday_rows._same("computer and information science", "computer science", "major")  # noqa: SLF001
    assert workday_rows._same("computer science", "computer and information science", "major")  # noqa: SLF001
    assert not workday_rows._same("stanford university", "uc irvine", "school")  # noqa: SLF001


def test_a_row_rendered_after_the_wait_is_still_returned(monkeypatch):
    class _SlowPage(_Page):
        waits = 0

        def evaluate(self, script, arg):
            if script == workday_rows._ADD_BUTTON_JS:  # noqa: SLF001
                return 0
            return super().evaluate(script, arg)

        def wait_for_timeout(self, ms):
            self.waits += 1
            if ms == 1500:  # the late look: the row has rendered by now
                self.values["education-2--schoolName"] = ""

    page = _SlowPage({"education-1--schoolName": "UC Irvine"})
    monkeypatch.setattr(repeaters.clicks, "safe_click", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "locator", lambda _s: _AddButton(), raising=False)
    assert workday_rows._add_row(page, "Education", "schoolName") == "education-2--"  # noqa: SLF001


class _AddButton:
    """The ``[data-rt-add]`` button `_press_add` clicks."""

    @property
    def first(self) -> _AddButton:
        return self

    def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        pass


class _AddPage(_Page):
    """A page whose section Add buttons exist; each press adds an education row unless
    ``blocked`` presses remain (a popup's dismiss layer over the button)."""

    def __init__(self, values: dict[str, str], *, blocked: int = 0) -> None:
        super().__init__(values)
        self.blocked = blocked
        self.presses = 0
        self.dismissed = 0
        self.add_args: list[object] = []

    def evaluate(self, script, arg):
        if script == workday_rows._ADD_BUTTON_JS:  # noqa: SLF001
            self.add_args.append(arg)
            return 0
        return super().evaluate(script, arg)

    def locator(self, selector: str):
        if selector == "[data-rt-add]":
            return _AddButton()
        return super().locator(selector)

    def press(self) -> None:
        self.presses += 1
        if self.blocked:
            self.blocked -= 1
            raise TimeoutError(
                "Locator.click: Timeout 5000ms exceeded.\n"
                "  - <div data-automation-id=\"click_filter\"></div> intercepts pointer events"
            )
        n = 1 + max((int(k.split("-")[1]) for k in self.values if k.startswith("education-")), default=0)
        self.values[f"education-{n}--schoolName"] = ""

    def dismiss(self, _page) -> bool:
        self.dismissed += 1
        return True


def test_a_blocked_add_press_is_retried_after_closing_the_popup(monkeypatch):
    # F5 (2026-09): the Skills prompt's dismiss layer sat over the Add buttons and every
    # press timed out. The popup is closed and the press tried once more.
    page = _AddPage({}, blocked=1)
    monkeypatch.setattr(repeaters.clicks, "safe_click", lambda *_a, **_k: page.press())
    row = workday_rows._add_row(page, "Education", "schoolName", dismiss=page.dismiss)  # noqa: SLF001
    assert row == "education-1--"
    assert (page.presses, page.dismissed) == (2, 1)
    # Only the visible button under the heading is marked and clicked by its tag.
    assert page.add_args == [["Education", True], ["Education", True]]


def test_an_add_press_that_stays_blocked_names_the_blocker_once_per_section(monkeypatch):
    page = _AddPage({}, blocked=99)
    monkeypatch.setattr(repeaters.clicks, "safe_click", lambda *_a, **_k: page.press())
    monkeypatch.setattr(workday_dates, "_fill_date", lambda *_a, **_k: True)
    packet = SimpleNamespace(experience=[], education=[_edu("UC Irvine", "Computer Science"),
                                                        _edu("Irvine Valley College", "Mathematics")])
    messages: list[str] = []
    filled, review = repeaters.fill(page, packet, messages.append, dismiss=page.dismiss)
    assert filled == []
    assert len(review) == 2
    assert all("Add button not clickable" in item and "intercepts pointer events" in item for item in review)
    # One press plus one retry for the section; the second entry does not wait again.
    assert page.presses == 2
    assert any("intercepts pointer events" in message for message in messages)


def test_an_education_row_without_year_controls_is_not_flagged(monkeypatch):
    # F5 (2026-09) asks school, degree, field of study and GPA, but no years attended.
    page = _Page({"education-1--schoolName": "", "education-1--fieldOfStudy": ""})
    monkeypatch.setattr(
        workday_dates,
        "_text_or_prompt",
        lambda _p, row, field, value, *, key: workday_dates._blank_fill(page, row, field, value),
    )  # noqa: SLF001
    monkeypatch.setattr(workday_dates, "_fill_date", lambda *_a, **_k: False)  # would fail if tried
    packet = SimpleNamespace(experience=[], education=[_edu("UC Irvine", "Computer Science")])
    filled, review = repeaters.fill(page, packet, lambda _m: None)
    assert review == []
    assert [item["label"] for item in filled] == ["Education: UC Irvine"]


class _FrontPage(_Page):
    """Keys sent while the tab is behind are lost; `bring_to_front` makes them land."""

    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.fronted = 0

    def evaluate(self, script, arg=None):
        if script == "() => document.hasFocus()":
            return False
        return super().evaluate(script, arg)

    def bring_to_front(self) -> None:
        self.fronted += 1
        self.drop_typing = 0


def test_a_date_lost_in_a_background_tab_is_retyped_in_front():
    # Invesco (2026-10): one row's From/To stayed empty while three fills shared a window.
    page = _FrontPage({f"{_START}Month-input": "", f"{_START}Year-input": ""})
    page.drop_typing = 2  # both background attempts at the month are lost
    notes: list[str] = []
    assert workday_dates._fill_date_retrying(  # noqa: SLF001
        page, "workExperience-1--", "startDate", "2025-01", with_month=True, note=notes.append,
    )
    assert page.fronted == 1
    assert page.values[f"{_START}Month-input"] == "01"
    assert page.values[f"{_START}Year-input"] == "2025"
    assert "page had focus: False" in notes[0] and notes[0].endswith("filled")


def test_a_date_that_lands_is_not_brought_to_front():
    page = _FrontPage({f"{_START}Month-input": "", f"{_START}Year-input": ""})
    assert workday_dates._fill_date_retrying(  # noqa: SLF001
        page, "workExperience-1--", "startDate", "2025-01", with_month=True, note=lambda _m: None,
    )
    assert page.fronted == 0


def test_an_add_press_that_shows_no_new_row_uses_the_row_rendered_late(monkeypatch):
    # AmerisourceBergen (2026-10): two employment rows were silently dropped when Add
    # showed no single new row in time. The late blank row is used; no review line.
    page = _Page(_work_rows(("Analyst", "Acme")))
    presses: list[str] = []

    def add_row(_page, heading, _anchor, **_kw):
        presses.append(heading)
        page.values["workExperience-2--jobTitle"] = ""  # rendered after the wait
        page.values["workExperience-2--companyName"] = ""
        return None

    monkeypatch.setattr(workday_rows, "_add_row", add_row)
    monkeypatch.setattr(workday_dates, "_fill_date", lambda *_a, **_k: True)
    packet = SimpleNamespace(education=[], experience=[
        SimpleNamespace(title="Analyst", employer="Acme", location="", description="",
                        start="2024-01", end="2024-06", current=False),
        SimpleNamespace(title="Engineer", employer="Initech", location="", description="",
                        start="2025-01", end="2025-06", current=False),
    ])
    filled, review = repeaters.fill(page, packet, lambda _m: None)
    assert review == []
    assert presses == ["Work Experience"]  # the late row was used, not a second press
    assert page.values["workExperience-2--jobTitle"] == "Engineer"
    assert [f["label"] for f in filled][-1] == "Work experience: Engineer at Initech"


def test_recover_row_presses_add_again_when_nothing_rendered():
    page = _Page(_work_rows(("Analyst", "Acme")))
    again: list[int] = []

    def press_again():
        again.append(1)
        page.values["workExperience-2--jobTitle"] = ""
        return "workExperience-2--"

    row = workday_rows._recover_row(page, "jobTitle", {"workExperience-1--"}, press_again)  # noqa: SLF001
    assert row == "workExperience-2--" and again == [1]


def test_dates_cleared_by_a_later_row_are_retyped_before_continue(monkeypatch):
    calls: list[tuple[str, str]] = []
    landed: set[tuple[str, str]] = set()

    def fill_date(_page, prefix, field, _value, *, with_month):
        calls.append((prefix, field))
        if (prefix, field) == ("workExperience-1--", "startDate") and (prefix, field) in landed:
            landed.discard((prefix, field))  # a later row's re-render cleared it once
            return False
        landed.add((prefix, field))
        return True

    page = _FrontPage(_work_rows(("Analyst", "Acme")))
    monkeypatch.setattr(workday_dates, "_fill_date", fill_date)
    packet = SimpleNamespace(education=[], experience=[
        SimpleNamespace(title="Analyst", employer="Acme", location="", description="",
                        start="2024-01", end="2024-06", current=False),
    ])
    filled, review = repeaters.fill(page, packet, lambda _m: None)
    assert review == []
    assert [f["label"] for f in filled] == ["Work experience: Analyst at Acme"]
    assert calls.count(("workExperience-1--", "startDate")) == 3  # fill, re-check, retype
