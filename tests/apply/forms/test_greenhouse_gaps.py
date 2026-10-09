"""Regression proof for the live Greenhouse failures diagnosed on 2026-10-09."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import form_facts, hybrid_resolver, questions
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.ats import ats_hints
from resume_tailor.apply.forms import attachments, fill_finish, fill_repairs, fill_widgets
from resume_tailor.apply.forms.field_types import FieldObservation
from resume_tailor.apply.funnel.packet_fields import build_fields
from resume_tailor.apply.funnel.packet_models import Packet, PacketEducation
from tests.fixtures import synthetic_resume

ROOT = Path(__file__).parents[3]
FILLER = (ROOT / "src/resume_tailor/apply/forms/filler.js").read_text(encoding="utf-8")
READY = (ROOT / "src/resume_tailor/apply/forms/filler_readiness.js").read_text(encoding="utf-8")
FIXTURE = (ROOT / "tests/fixtures/forms/greenhouse_application_gaps.html").read_text(
    encoding="utf-8"
)


@pytest.fixture
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="msedge")
        try:
            page = browser.new_page()
            page.set_content(FIXTURE)
            yield page
        finally:
            browser.close()


def test_captured_greenhouse_questions_fill_supported_facts(page):
    fields = {
        "high_school_graduation_year": "2023",
        "class_year": "Senior",
        "relatives_at_company": "No",
        "auto_accept_routine_acknowledgements": "Yes",
        "phone_country_code": "+1",
        "phone_country_region": "United States",
    }
    args = {"fields": fields, "hints": {}, "synonyms": ats_hints.SYNONYMS}
    scanned = page.evaluate(FILLER, {**args, "scan": True})
    plan = questions.plan_for(
        scanned["questions"], questions.Facts(fields, skills=("Python", "C++"))
    )
    assert plan["#country"]["key"] == "phone_country_code"
    assert plan["#java"]["values"] == ["C++", "Python"]
    page.evaluate(FILLER, {**args, "plan": plan})
    assert page.locator("#high-school").input_value() == "2023"
    assert page.locator("#grade").input_value() == "Senior"
    assert page.locator("#relatives").input_value() == "No"
    assert page.locator("#read-notice").input_value() == "Yes"
    assert page.locator("#privacy").is_checked()
    assert page.locator("#cpp").is_checked() and page.locator("#python").is_checked()
    assert not page.locator("#java").is_checked() and not page.locator("#none").is_checked()
    assert page.evaluate(READY, {}) == []


def test_transcript_uses_question_not_attach_caption(page):
    result = page.evaluate(FILLER, {"fields": {}, "hints": {}, "synonyms": ats_hints.SYNONYMS})
    item = next(x for x in result["file_inputs"] if x["selector"] == "#question_transcript")
    assert fill_widgets._attachment_purpose(item["label"], item["selector"], {}) == "transcript"


def test_routine_notices_require_preference_and_full_context(page):
    args = {"fields": {}, "hints": {}, "synonyms": ats_hints.SYNONYMS}
    scan = page.evaluate(FILLER, {**args, "scan": True})
    plan = questions.plan_for(scan["questions"], questions.Facts({}))
    page.evaluate(FILLER, {**args, "plan": plan})
    assert not page.locator("#privacy").is_checked()
    assert page.locator("#read-notice").input_value() == ""
    assert (
        form_facts.acknowledgement("I certify this application is accurate. Privacy policy")
        == "manual"
    )
    assert form_facts.acknowledgement("Acknowledge/Confirm") == "manual"


def test_readiness_accepts_chips_and_ignores_internal_required_input(page):
    page.set_content(
        '<label for="skills">Skills</label><div class="select__control"><div class="select__multi-value">Python</div><input id="skills" role="combobox" required><input required></div>'
    )
    assert page.evaluate(READY, {}) == []
    page.locator(".select__multi-value").evaluate("e=>e.remove()")
    assert page.evaluate(READY, {}) == ["Skills"]


@pytest.mark.parametrize(
    "year,expected", [("2020", "Before 2021"), ("2023", "2023"), ("2025", None)]
)
def test_high_school_year_matches_offered_ranges(year, expected):
    assert form_facts.year_option(["Before 2021", "2023"], year) == expected
    assert (
        questions.classify(questions.Question("When did you graduate from High School?")).key
        == form_facts.HIGH_SCHOOL
    )


def test_skill_matching_preserves_punctuation():
    assert form_facts.skill_options(
        ["C", "C++", "C#", "Python (Programming Language)"], ["C++", "Python"]
    ) == ["C++", "Python (Programming Language)"]


def test_high_school_unmatched_boundary_stays_unanswered():
    plan = questions.plan_for([{"selector": "#hs", "label": "When did you graduate high school?",
                               "kind": "choice", "options": ["Before 2021", "2022"]}],
                              questions.Facts({form_facts.HIGH_SCHOOL: "2021"}))
    assert plan['#hs']['value'] is None
    assert form_facts.year_option(['2021 or before', '2022'], '2021') == '2021 or before'


def test_privacy_notice_with_certification_option_is_manual():
    question = questions.Question('I agree to the privacy notice', kind='choice',
        options=('Yes, I certify this application is accurate', 'No'))
    assert questions.answers(questions.classify(question), question,
        questions.Facts({'auto_accept_routine_acknowledgements': 'Yes'})) == []


def test_high_school_default_uses_earliest_undergraduate_start_and_override():
    rows = [
        PacketEducation(start="2024-09", degree_level="Bachelor of Science"),
        PacketEducation(start="2022-09", degree_level="Associate of Science"),
        PacketEducation(start="2020-09", degree_level="Master of Science"),
    ]
    assert form_facts.high_school_year(rows) == "2022"
    resume = synthetic_resume()
    fields = build_fields(
        ApplicantProfile(high_school_graduation_year="2021", relatives_at_company=False), resume
    )
    assert fields[form_facts.HIGH_SCHOOL] == "2021"
    assert fields["relatives_at_company"] == "No"
    with pytest.raises(ValueError):
        ApplicantProfile(high_school_graduation_year="unknown")


def test_relative_names_are_not_invented():
    q = questions.Question(
        "Do you have relatives working for Example? If yes, list name and relationship."
    )
    assert (
        questions.answers(
            questions.classify(q), q, questions.Facts({"relatives_at_company": "Yes"})
        )
        == []
    )


def test_successful_empty_final_scan_does_not_restore_old_missing_fields():
    frame = SimpleNamespace(evaluate=lambda *a: [])
    state = SimpleNamespace(
        page=SimpleNamespace(frames=[frame]),
        readiness_js="ready",
        merged={"required_empty": ["Old question"], "leftovers": []},
    )
    assert fill_finish._FillFinish._final_required_empty(state) == []


def test_failed_final_scan_still_blocks_readiness():
    def fail(*args):
        raise RuntimeError("frame lost")

    state = SimpleNamespace(
        page=SimpleNamespace(frames=[SimpleNamespace(evaluate=fail)]),
        readiness_js="ready",
        merged={"leftovers": []},
    )
    assert fill_finish._FillFinish._final_required_empty(state)


def test_known_start_month_never_goes_to_model_or_cached_guess(monkeypatch):
    pkt = Packet(job_id="test", built_at="", fields={"education_start_month": "2023-09"})
    resolver = hybrid_resolver._StepResolver(
        None,
        pkt,
        ApplicantProfile(),
        max_retries=1,
        on_progress=None,
        deadline=None,
        ledger=hybrid_resolver.resolver_types.StepLedger(),
        only_invalid=False,
    )
    selected = []
    monkeypatch.setattr(
        hybrid_resolver.widget_actions,
        "_select_combobox_option",
        lambda *args, **kwargs: selected.append(args[2]) or True,
    )
    assert (
        resolver._resolve_known(
            [
                {
                    "type": "combobox",
                    "selector": "#start-month--0",
                    "label": "Start date month*",
                    "options": ["June", "September"],
                }
            ]
        )
        == []
    )
    assert selected == ["September"]


def test_uncommitted_known_date_blocks_resolver_success(monkeypatch):
    pkt = Packet(job_id='test', built_at='', fields={'education_start_month': '2023-09'})
    field = {'type': 'combobox', 'selector': '#start', 'label': 'Start date month',
             'options': ['June', 'September']}
    resolver = hybrid_resolver._StepResolver(None, pkt, ApplicantProfile(), max_retries=1,
        on_progress=None, deadline=None, ledger=hybrid_resolver.resolver_types.StepLedger(), only_invalid=False)
    monkeypatch.setattr(hybrid_resolver.page_blockers, 'extract_page_blockers',
                        lambda page: {'unresolved': [field]})
    monkeypatch.setattr(resolver, '_load_options', lambda fields: None)
    monkeypatch.setattr(hybrid_resolver.widget_actions, '_select_combobox_option', lambda *a, **k: False)
    assert resolver.run() is False


def test_routine_checkbox_group_cannot_bypass_preference_in_model_fallback():
    pkt = Packet(job_id='test', built_at='', fields={})
    resolver = hybrid_resolver._StepResolver(None, pkt, ApplicantProfile(), max_retries=1,
        on_progress=None, deadline=None, ledger=hybrid_resolver.resolver_types.StepLedger(), only_invalid=False)
    assert resolver._resolve_known([{'type': 'checkboxgroup', 'selector': '#privacy',
                                    'label': 'I agree to the privacy notice'}]) == []
    assert '#privacy' in resolver.ledger.asked


def test_cache_key_includes_context_and_help():
    field = {"label": "Q", "type": "combobox", "options": ["C++"]}
    key = hybrid_resolver._choice_key(field, "facts1")
    assert key != hybrid_resolver._choice_key(field, "facts2")
    assert key != hybrid_resolver._choice_key({**field, "help": "privacy notice"}, "facts1")
    assert key != hybrid_resolver._choice_key({**field, "options": ["C"]}, "facts1")


def test_verified_upload_recognizes_transcript_and_correct_source():
    f = FieldObservation(
        snapshot_id="",
        field_id="file",
        frame_id="main",
        document_generation="",
        label="Attach",
        help_text="Upload your transcript",
    )
    assert attachments.purpose_for(f) == "transcript"
    pkt = Packet(job_id="test", built_at="", artifacts={"transcript_pdf": "transcript.pdf"})
    assert attachments._source(pkt, "transcript", ".pdf") == "transcript.pdf"


def test_phone_country_outside_first_options_is_searched_and_verified(page):
    from resume_tailor.apply.answers import widget_actions

    page.set_content("""
      <div class="select__control"><span class="select__single-value"></span>
      <input id="dial" role="combobox" aria-controls="dial-menu"></div>
      <div id="dial-menu" role="listbox" hidden></div>
      <script>
      let selected = ''; const input = document.querySelector('#dial');
      const menu = document.querySelector('#dial-menu');
      function render(term = '') {
        menu.hidden = false; menu.innerHTML = '';
        const labels = term.toLowerCase().includes('united')
          ? ['United States +1'] : ['Canada +1', ...Array.from({length: 55}, (_, i) => 'Country ' + i + ' +' + (20+i))];
        for (const label of labels) {
          const option = document.createElement('div'); option.setAttribute('role', 'option');
          option.setAttribute('aria-selected', String(label === selected)); option.textContent = label;
          option.onclick = () => {selected = label; input.value = '';
            document.querySelector('.select__single-value').textContent = '+1'; menu.hidden = true;};
          menu.append(option);
        }
      }
      input.onclick = () => render(selected.includes('United') ? 'United' : '');
      input.oninput = () => render(input.value);
      input.onkeydown = e => {if (e.key === 'Escape') menu.hidden = true;};
      </script>
    """)
    pkt = Packet(job_id="test", built_at="", fields={})
    resolver = hybrid_resolver._StepResolver(
        page,
        pkt,
        ApplicantProfile(phone_country_code="+1", phone_country_region="United States"),
        max_retries=1,
        on_progress=None,
        deadline=None,
        ledger=hybrid_resolver.resolver_types.StepLedger(),
        only_invalid=False,
    )
    unresolved = [
        {
            "selector": "#dial",
            "type": "combobox",
            "label": "Country",
            "options": ["Canada +1", "France +33"],
        }
    ]
    assert resolver._select_phone_codes(unresolved) == []
    assert "#dial" in resolver.ledger.done
    assert page.evaluate("selected") == "United States +1"
    assert widget_actions._selected_combobox_text(page.locator("#dial")) == "+1"


@pytest.mark.parametrize("current,expected", [("June", "September"), ("August", "August")])
def test_continue_repairs_automation_but_preserves_manual_dates(page, current, expected):
    page.set_content("""
      <div class="select__control"><span class="select__single-value">June</span>
      <input id="start" role="combobox" aria-controls="months"></div><div id="months" role="listbox" hidden>
      <div role="option">June</div><div role="option">September</div></div>
      <script>
      const menu = document.querySelector('#months');
      document.querySelector('#start').onclick = () => menu.hidden = false;
      for (const option of menu.children) option.onclick = () => {
        document.querySelector('.select__single-value').textContent = option.textContent; menu.hidden = true;};
      </script>
    """)
    page.locator(".select__single-value").evaluate("(el, value) => el.textContent = value", current)
    prior = [{"selector": "#start", "label": "Start date month", "value": "June", "key": "hybrid"}]
    repaired = fill_repairs.correct_previous_answers(
        page, prior, questions.Facts({"education_start_month": "2023-09"})
    )
    assert page.locator(".select__single-value").inner_text() == expected
    assert bool(repaired) == (current == "June")


def test_async_scanner_and_actions_fill_same_greenhouse_gaps(tmp_path):
    import asyncio

    from playwright.async_api import async_playwright

    from resume_tailor.apply.ats.adapters import GreenhouseAdapter
    from resume_tailor.apply.driver import controls, scanner

    async def run():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, channel="msedge")
            try:
                page = await browser.new_page()
                await page.set_content(FIXTURE)
                fields = {
                    "high_school_graduation_year": "2023",
                    "class_year": "Senior",
                    "relatives_at_company": "No",
                    "auto_accept_routine_acknowledgements": "Yes",
                }
                pkt = Packet(
                    job_id="test", built_at="", fields=fields, master_skills=["Python", "C++"]
                )
                adapter = GreenhouseAdapter()
                for selector in [
                    "high-school",
                    "java",
                    "grade",
                    "relatives",
                    "read-notice",
                    "privacy",
                ]:
                    snapshot = await scanner.scan(page)
                    field = next(f for f in snapshot.fields if f.constraints.get("id") == selector)
                    policy, key = adapter.classify(field)
                    assert policy == "known", field
                    field.canonical_key = key
                    value = adapter.value_for(field, key, pkt, fields)
                    outcome = await controls.apply_value(
                        page, snapshot, field, value, phone_region="United States"
                    )
                    assert outcome.state == "verified_filled", outcome
                assert await page.locator("#cpp").is_checked()
                assert await page.locator("#python").is_checked()
                assert not await page.locator("#none").is_checked()
                transcript = tmp_path / "source-transcript.pdf"
                transcript.write_bytes(b"%PDF-1.4 fixture")
                pkt.artifacts["transcript_pdf"] = str(transcript)
                snapshot = await scanner.scan(page)
                upload = next(f for f in snapshot.fields if f.control_kind == "file")
                import time

                result = await attachments.upload(
                    snapshot,
                    upload,
                    pkt,
                    applicant_name="Alex Doe",
                    role="Intern",
                    out_dir=tmp_path / "fill",
                    deadline=time.monotonic() + 10,
                )
                assert result.state == "verified" and result.purpose == "transcript"
                assert "Transcript" in result.observed_filename
                snapshot = await scanner.scan(page)
                upload = next(f for f in snapshot.fields if f.control_kind == "file")
                kept = await attachments.upload(
                    snapshot,
                    upload,
                    pkt,
                    applicant_name="Alex Doe",
                    role="Intern",
                    out_dir=tmp_path / "fill",
                    deadline=time.monotonic() + 10,
                )
                assert kept.state == "preserved"
                assert kept.observed_filename == result.observed_filename
            finally:
                await browser.close()

    asyncio.run(run())
