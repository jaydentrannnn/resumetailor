"""`smartrecruiters_flow` against the one-click form's captured markup (runs in installed Edge).

Fixtures under ``tests/fixtures/smartrecruiters/`` are the live form's structure (open
shadow roots kept as declarative ``<template shadowrootmode>``), captured 2026-09-27 from
jobs.smartrecruiters.com/Resultant/744000151474767 and /WellmarkInc/744000150732768 with
personal data replaced; ``screening_resultant.html`` is the Resultant form's second step
(a subset of its questions, the page's question ``definition`` JSON removed and its
select options kept in ``screening_options.json``). ``behaviour.js`` stands in for the components' scripts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from resume_tailor.apply import smartrecruiters_flow as sr
from resume_tailor.apply.packet import Packet, PacketEducation, PacketExperience

_DIR = Path(__file__).parent / "fixtures" / "smartrecruiters"
_URL = "https://jobs.smartrecruiters.com/oneclick-ui/company/Acme/publication/abc"


def _fixture(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


def _entry(section_html: str, tag: str) -> str:
    start = section_html.index(f"<{tag}")
    end = section_html.index(f"</{tag}>", start) + len(f"</{tag}>")
    return section_html[start:end]


_LOCATIONS = {
    "US_CA_CITY_fountain_valley": {
        "locationType": "city", "id": "US_CA_CITY_fountain_valley", "countryCode": "US",
        "country": "United States", "text": "Fountain Valley, CA, US",
        "displayString": "Fountain Valley, CA, US", "city": "Fountain Valley",
        "region": "California", "stateCode": "CA",
    },
    "US_CA_CITY_glendale": {
        "id": "US_CA_CITY_glendale", "countryCode": "US", "country": "United States",
        "displayString": "Glendale, CA, US", "city": "Glendale", "region": "California", "stateCode": "CA",
    },
    "US_AZ_CITY_glendale": {
        "id": "US_AZ_CITY_glendale", "countryCode": "US", "country": "United States",
        "displayString": "Glendale, AZ, US", "city": "Glendale", "region": "Arizona", "stateCode": "AZ",
    },
    "US_IL_CITY_springfield": {
        "id": "US_IL_CITY_springfield", "countryCode": "US", "country": "United States",
        "displayString": "Springfield, IL, US", "city": "Springfield", "region": "Illinois", "stateCode": "IL",
    },
    "US_MO_CITY_springfield": {
        "id": "US_MO_CITY_springfield", "countryCode": "US", "country": "United States",
        "displayString": "Springfield, MO, US", "city": "Springfield", "region": "Missouri", "stateCode": "MO",
    },
}
_CATALOG = {"institution-autocomplete": [["State University", "State University"],
                                         ["State University School of Law", "State University School of Law"]]}


def _launch(playwright):
    """Installed Edge, else Playwright's Chromium (``PW_CHROMIUM_PATH`` names its binary)."""
    try:
        return playwright.chromium.launch(headless=True, channel="msedge")
    except Exception:
        path = os.environ.get("PW_CHROMIUM_PATH")
        return playwright.chromium.launch(headless=True, executable_path=path or None)


@pytest.fixture(scope="module")
def browser():
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            launched = _launch(playwright)
            try:
                yield launched
            finally:
                launched.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


def _open(browser, form: str = "form_resultant.html", *, replace: dict[str, str] | None = None,
          arrow_limit: int = 0):
    """The form served at a one-click URL (declarative shadow roots need a real parse)."""
    body = _fixture(form)
    for section, html in (replace or {}).items():
        start = body.index(f'<div data-test="{section}"')
        # A section ends where the next top-level section begins.
        end = body.index('<div data-test="', body.index("</ul>", start))
        body = body[:start] + html.strip() + body[end:]
    editors = {
        "experience": _entry(_fixture("experience_editor.html"), "oc-experience-entry"),
        "education": _entry(_fixture("education_editor.html"), "oc-education-entry"),
    }
    state = {"catalog": _CATALOG, "locations": _LOCATIONS, "editors": editors,
             "selects": json.loads(_fixture("screening_options.json")), "arrowLimit": arrow_limit}
    page = browser.new_page()
    html = (f"<!doctype html><html><body><main>{body}</main>"
            f"<script>window.__sr = {json.dumps(state)};</script>"
            f"<script>{_fixture('behaviour.js')}</script></body></html>")
    page.route("**/oneclick-ui/**", lambda route: route.fulfill(body=html, content_type="text/html"))
    page.goto(_URL)
    return page


def _packet(**changes) -> Packet:
    base = Packet(
        job_id="job", built_at="now", ats="smartrecruiters",
        fields={"city": "Fountain Valley", "state": "California", "country": "United States"},
        experience=[PacketExperience(
            title="Data Intern", employer="Acme Corp", location="Glendale, California",
            start="2025-06", end="2025-09", description="Built dashboards.",
        )],
        education=[PacketEducation(
            school="State University", degree_level="Bachelor of Science", major="Computer Science",
            start="2023-09", end="2027-06",
        )],
        cover_letter="I would like to join the team.",
    )
    return base.model_copy(update=changes)


def _no_progress(_message: str) -> None:
    pass


# --- pure helpers ---------------------------------------------------------------------


def test_month_year_is_the_pickers_typed_format():
    assert sr.month_year("2026-06") == "06/2026"
    assert sr.month_year("2026-6-01") == "06/2026"
    assert sr.month_year("2026") == ""  # no month: left for review, never guessed
    assert sr.month_year("") == ""


def test_split_location_tells_a_state_from_a_country():
    assert sr.split_location("Glendale, California") == ("Glendale", "California", "United States")
    assert sr.split_location("Irvine, CA") == ("Irvine", "CA", "United States")
    assert sr.split_location("Ho Chi Minh City, Vietnam") == ("Ho Chi Minh City", "", "Vietnam")
    assert sr.split_location("") == ("", "", "")


def test_pick_location_needs_one_city_in_the_right_state():
    options = [("US_AZ_CITY_glendale", "Glendale, AZ, US"), ("US_CA_CITY_glendale", "Glendale, CA, US"),
               ("goToManualLocationMode", "Cannot find your city? Click here to fill in manually")]
    assert sr.pick_location(options, "Glendale", "California") == "US_CA_CITY_glendale"
    assert sr.pick_location(options, "Glendale", "CA") == "US_CA_CITY_glendale"
    assert sr.pick_location(options, "Glendale") is None  # two Glendales: not confident
    assert sr.pick_location(options, "Irvine", "California") is None
    assert sr.pick_location([options[2]], "Cannot find your city? Click here to fill in manually") is None
    vn = [("VN_SG_CITY_ho_chi_minh_city", "Ho Chi Minh City, SG, VN")]
    assert sr.pick_location(vn, "Ho Chi Minh City", "", "Vietnam") == "VN_SG_CITY_ho_chi_minh_city"
    assert sr.pick_location(vn, "Ho Chi Minh City", "", "United States") is None


def test_pick_text_prefers_the_catalog_spelling_then_the_typed_text():
    options = [("#spl-custom-option", "Acme"), ("Acme", "Acme Irvine, US")]
    assert sr.pick_text(options, "acme") == "Acme"
    assert sr.pick_text([("#spl-custom-option", "Acme Corp")], "Acme Corp") == "#spl-custom-option"
    assert sr.pick_text([("Acme Holdings", "Acme Holdings")], "Acme") is None


def test_a_committed_location_is_checked_against_the_profile():
    committed = _LOCATIONS["US_CA_CITY_fountain_valley"]
    assert sr.location_matches(committed, "Fountain Valley", "California", "United States")
    assert sr.location_matches(committed, "Fountain Valley", "CA", "USA")
    assert not sr.location_matches(committed, "Fountain Valley", "Arizona")
    assert not sr.location_matches(committed, "Irvine")
    assert not sr.location_matches("Fountain Valley", "Fountain Valley")


# --- City ---------------------------------------------------------------------------


def test_city_commits_the_matching_option(browser):
    page = _open(browser)
    filled, review = sr.fill_city(page, _packet().fields)
    assert review == []
    assert filled == [{"label": "City", "value": "Fountain Valley, CA, US"}]
    host = page.locator(sr._LOCATION)
    assert host.evaluate("h => h.value.id") == "US_CA_CITY_fountain_valley"


def test_an_ambiguous_city_is_cleared_and_left_for_review(browser):
    page = _open(browser)
    filled, review = sr.fill_city(page, {"city": "Springfield", "state": "", "country": "United States"})
    assert filled == []
    assert review == ["City: no confident match for Springfield"]
    field = page.locator(f"{sr._LOCATION} input[role=combobox]")
    assert field.input_value() == ""  # no half-typed text that reads as filled


def test_a_committed_city_is_kept(browser):
    page = _open(browser)
    page.locator(sr._LOCATION).evaluate("(h, loc) => { h.value = loc; }", _LOCATIONS["US_IL_CITY_springfield"])
    filled, review = sr.fill_city(page, _packet().fields)
    assert review == []
    assert filled == [{"label": "City", "value": "Springfield, IL, US", "state": "preserved"}]
    assert page.locator(sr._LOCATION).evaluate("h => h.value.city") == "Springfield"


def test_a_form_without_a_city_asks_nothing(browser):
    page = _open(browser, "form_wellmark.html")
    assert sr.fill_city(page, _packet().fields) == ([], [])


# --- Experience ---------------------------------------------------------------------


def test_an_experience_entry_is_added_saved_and_listed(browser):
    page = _open(browser)
    filled, review = sr.fill_experience(page, _packet(), _no_progress)
    assert review == []
    assert filled == [{"label": "Experience 1 (Data Intern at Acme Corp)", "value": "Data Intern at Acme Corp"}]
    assert sr._entries(page, "experience") == [{"title": "Data Intern", "company": "Acme Corp"}]
    assert page.evaluate("window.__sr.saves") == 1


def test_a_listed_experience_entry_is_reused_not_duplicated(browser):
    page = _open(browser, replace={"experience": _fixture("experience_saved.html")})
    assert sr._entries(page, "experience") == [{"title": "Data Intern", "company": "Acme Corp"}]
    filled, review = sr.fill_experience(page, _packet(), _no_progress)
    assert review == []
    assert filled[0]["state"] == "preserved"
    assert page.evaluate("window.__sr.saves") == 0
    assert len(sr._entries(page, "experience")) == 1


def test_an_entry_already_open_for_editing_is_not_touched(browser):
    page = _open(browser, replace={"experience": _fixture("experience_editor.html")})
    filled, review = sr.fill_experience(page, _packet(), _no_progress)
    assert filled == []
    assert review == ["Experience: an entry is open for editing; finish it, then Continue fill"]
    assert page.evaluate("window.__sr.saves") == 0


def test_a_current_role_ticks_the_box_instead_of_an_end_date(browser):
    page = _open(browser)
    current = PacketExperience(title="Data Intern", employer="Acme Corp", start="2026-06", current=True)
    filled, review = sr.fill_experience(page, _packet(experience=[current]), _no_progress)
    assert review == []
    assert len(filled) == 1
    assert "Present" in page.locator("[data-test=experience-entry-date]").inner_text()


def test_an_entry_that_cannot_be_saved_is_left_open_with_the_rest_for_review(browser):
    page = _open(browser)
    undated = PacketExperience(title="Data Intern", employer="Acme Corp")  # To/From are required
    later = PacketExperience(title="Tutor", employer="Library", start="2024-01", end="2024-05")
    filled, review = sr.fill_experience(page, _packet(experience=[undated, later]), _no_progress)
    assert filled == []
    label = "Experience 1 (Data Intern at Acme Corp)"
    assert f"{label}: start date" in review
    assert f"{label}: not saved; complete the open entry and press Save" in review
    assert "Experience 2 (Tutor at Library)" in review
    assert page.locator("[data-test=experience-edit-form]").count() == 1


def test_an_unmatched_office_location_is_left_blank_and_flagged(browser):
    page = _open(browser)
    elsewhere = PacketExperience(title="Data Intern", employer="Acme Corp", location="Glendale",
                                 start="2025-06", end="2025-09")
    filled, review = sr.fill_experience(page, _packet(experience=[elsewhere]), _no_progress)
    # Two Glendales and no state: the entry is saved without an office location.
    assert review == ["Experience 1 (Data Intern at Acme Corp): office location (Glendale)"]
    assert filled[0]["state"] == "partial"


# --- Education ----------------------------------------------------------------------


def test_an_education_entry_is_added_with_the_catalog_school(browser):
    page = _open(browser)
    filled, review = sr.fill_education(page, _packet(), _no_progress)
    assert review == []
    assert filled == [{"label": "Education 1 (State University)", "value": "State University"}]
    assert sr._entries(page, "education") == [
        {"school": "State University", "major": "Computer Science", "degree": "Bachelor of Science"},
    ]


def test_a_listed_education_entry_is_reused(browser):
    page = _open(browser, replace={"education": _fixture("education_saved.html")})
    filled, review = sr.fill_education(page, _packet(), _no_progress)
    assert review == []
    assert filled[0]["state"] == "preserved"
    assert page.evaluate("window.__sr.saves") == 0


def test_a_second_degree_at_the_same_school_is_added(browser):
    page = _open(browser, replace={"education": _fixture("education_saved.html")})
    masters = PacketEducation(school="State University", degree_level="Master of Science",
                              major="Statistics", start="2027-09", end="2029-06")
    filled, review = sr.fill_education(page, _packet(education=[masters]), _no_progress)
    assert review == []
    assert "state" not in filled[0]
    assert len(sr._entries(page, "education")) == 2


# --- Resume -------------------------------------------------------------------------


def test_the_resume_goes_to_the_resume_dropzone_only(browser, tmp_path):
    resume = tmp_path / "Applicant_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n")
    page = _open(browser)
    filled, review = sr.fill_resume(page, str(resume))
    assert review == []
    assert filled == [{"label": "Resume", "value": "Applicant_Resume.pdf"}]
    # Never the "Easy Apply" dropzone, which parses the file and prefills the form.
    assert page.evaluate("window.__sr.uploads") == ["resume-upload:Applicant_Resume.pdf"]


def test_a_listed_resume_is_kept(browser, tmp_path):
    resume = tmp_path / "Applicant_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n")
    page = _open(browser, replace={"resume-upload-container": _fixture("resume_listed.html")})
    filled, review = sr.fill_resume(page, str(resume))
    assert review == []
    assert filled == [{"label": "Resume", "value": "resume.pdf", "state": "preserved"}]
    assert page.evaluate("window.__sr.uploads") == []


def test_a_missing_resume_file_is_left_for_review(browser, tmp_path):
    page = _open(browser)
    assert sr.fill_resume(page, str(tmp_path / "gone.pdf")) == ([], ["Resume: no prepared resume file to attach"])


# --- Message ------------------------------------------------------------------------


def test_the_cover_letter_goes_into_an_empty_message_box(browser):
    page = _open(browser)
    filled, review = sr.fill_message(page, "I would like to join the team.")
    assert review == []
    assert filled == [{"label": "Message to the Hiring Team", "value": "cover letter"}]
    assert page.locator(sr._MESSAGE).input_value() == "I would like to join the team."


def test_a_written_message_is_kept(browser):
    page = _open(browser)
    page.locator(sr._MESSAGE).fill("My own note.")
    filled, review = sr.fill_message(page, "I would like to join the team.")
    assert review == []
    assert filled[0]["state"] == "preserved"
    assert page.locator(sr._MESSAGE).input_value() == "My own note."


# --- Whole form ---------------------------------------------------------------------


def test_the_whole_form_is_filled_and_verified(browser, tmp_path):
    resume = tmp_path / "Applicant_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n")
    page = _open(browser)
    filled, review = sr.fill(page, _packet(), _no_progress, resume_path=str(resume))
    assert review == []
    assert [item["label"] for item in filled] == [
        "City", "Resume", "Message to the Hiring Team",
        "Experience 1 (Data Intern at Acme Corp)", "Education 1 (State University)",
    ]
    # Running it again adds nothing and keeps every answer.
    again, review = sr.fill(page, _packet(), _no_progress, resume_path=str(resume))
    assert review == []
    assert all(item["state"] == "preserved" for item in again)
    assert page.evaluate("window.__sr.saves") == 2


def test_past_the_deadline_no_entry_is_added(browser):
    page = _open(browser)
    filled, review = sr.fill_experience(page, _packet(), _no_progress, deadline=0.0)
    assert filled == []
    assert review == ["Experience 1 (Data Intern at Acme Corp)"]


def test_the_wellmark_form_has_no_city_but_every_other_area(browser, tmp_path):
    resume = tmp_path / "Applicant_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n")
    page = _open(browser, "form_wellmark.html")
    filled, review = sr.fill(page, _packet(), _no_progress, resume_path=str(resume))
    assert review == []
    assert [item["label"] for item in filled] == [
        "Resume", "Message to the Hiring Team",
        "Experience 1 (Data Intern at Acme Corp)", "Education 1 (State University)",
    ]


# --- Screening step ---------------------------------------------------------------------

_SCREENING_FIELDS = {
    "authorized_to_work": "Yes", "requires_sponsorship_future": "No",
    "degree_level": "Bachelors", "degree_name": "Bachelor of Science", "major": "Computer Science",
    "school": "State University", "graduation_month": "2027-06", "salary_hourly": "$30/hour",
    "how_heard": "LinkedIn", "veteran_status": "not_veteran",
}


@pytest.fixture
def no_memory(monkeypatch):
    monkeypatch.setattr(sr.answer_memory, "recall", lambda *_args, **_kwargs: None)


def test_screening_questions_are_answered_from_profile_facts(browser, no_memory):
    page = _open(browser, "screening_resultant.html")
    filled, review = sr.fill_screening(page, _packet(fields=_SCREENING_FIELDS), _no_progress)
    answers = {item["label"][:40]: item["value"] for item in filled}
    assert answers == {question[:40]: value for question, value in [
        ("Are you authorized to work and accept new employment in the United States?", "Yes"),
        ("Will you need sponsorship in the future from an employer", "No"),
        ("What is your current or most recently completed degree type?", "Bachelor's Degree"),
        ("What is your current or most recent major?", "Computer Science & Programming"),
        ("What is the name of your school?", "State University"),
        ("What is your expected graduation month?", "June"),
        ("What is your expected graduation year?", "2027"),
        ("What is your hourly wage expectation?", "$30/hour"),
        ("How did you learn about Resultant and this opportunity?", "LinkedIn"),
        ("Are you a veteran?", "No"),
    ]}
    # No profile fact answers a non-compete; declarations are the applicant's to tick.
    assert review[0] == "Are you currently subject to a non-compete agreement?: no answer in the applicant profile"
    assert review[1:] == [
        "*I declare that all statements and answers in this application are true and complete an...: "
        "read and tick it yourself",
    ]
    assert page.evaluate("""() => {
      const deep = (root, out = []) => { out.push(...root.querySelectorAll('input[type=checkbox]'));
        for (const el of root.querySelectorAll('*')) if (el.shadowRoot) deep(el.shadowRoot, out); return out; };
      return deep(document).filter((box) => box.checked).length;
    }""") == 0
    degree = page.locator("spl-autocomplete#question_89501da0-cb06-433c-a168-316a602e3644")
    assert degree.evaluate("h => h.value") == "cc41e0d5-bb5b-4b54-a16c-1703c41fc243"


def test_screening_keeps_answers_already_given(browser, no_memory):
    page = _open(browser, "screening_resultant.html")
    sr.fill_screening(page, _packet(fields=_SCREENING_FIELDS), _no_progress)
    clicks = page.evaluate("window.__sr.radioClicks")
    filled, _review = sr.fill_screening(page, _packet(fields={**_SCREENING_FIELDS, "authorized_to_work": "No"}), _no_progress)
    assert page.evaluate("window.__sr.radioClicks") == clicks
    kept = {item["label"]: item for item in filled}
    work = kept["Are you authorized to work and accept new employment in the United States?"]
    assert (work["value"], work["state"]) == ("Yes", "preserved")


def test_an_option_no_answer_names_is_left_for_review(browser, no_memory):
    page = _open(browser, "screening_resultant.html")
    fields = {"major": "Mathematics and Computer Science"}
    filled, review = sr.fill_screening(page, _packet(fields=fields), _no_progress)
    assert filled == []
    assert "What is your current or most recent major?: could not set 'Mathematics and Computer Science'" in review
    major = page.locator("spl-autocomplete#question_867d31ec-87ef-49f2-8c11-1f9fb51f9df5")
    assert major.evaluate("h => h.value") in (None, "")


def test_a_long_select_is_searched_when_its_first_options_miss(browser, no_memory):
    # AbbVie (2026-09): the majors list opens on its first few options only.
    page = _open(browser, "screening_resultant.html", arrow_limit=5)
    filled, _review = sr.fill_screening(page, _packet(fields=_SCREENING_FIELDS), _no_progress)
    answered = {item["label"]: item["value"] for item in filled}
    assert answered["What is your current or most recent major?"] == "Computer Science & Programming"
    major = page.locator("spl-autocomplete#question_867d31ec-87ef-49f2-8c11-1f9fb51f9df5")
    assert major.evaluate("h => h.value")


def test_a_remembered_answer_covers_a_question_the_profile_does_not(browser, monkeypatch):
    remembered = {"are you currently subject to a non compete agreement": "No"}

    def recall(label, **_kwargs):
        from resume_tailor.apply.answer_memory import Recall, normalize_label

        answer = remembered.get(normalize_label(label))
        return Recall(answer=answer, id=1) if answer else None

    monkeypatch.setattr(sr.answer_memory, "recall", recall)
    page = _open(browser, "screening_resultant.html")
    filled, review = sr.fill_screening(page, _packet(fields={}, company="Resultant"), _no_progress)
    assert {"label": "Are you currently subject to a non-compete agreement?", "value": "No"} in filled
    assert not any("non-compete" in line for line in review)

