"""Filled answers a form refuses: `page_blockers` reports them apart (shadow roots too),
`rejected_repair` types the same value again in another shape, and what no shape fixes
becomes a review note. Runs in installed Edge, offline."""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import sync_playwright

from resume_tailor.apply.answers import (
    hybrid_resolver,
    page_blockers,
    rejected_repair,
    resolver_types,
    widget_actions,
)
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.funnel.packet_models import Packet


@pytest.fixture(scope="module")
def browser():
    try:
        with sync_playwright() as playwright:
            try:
                launched = playwright.chromium.launch(headless=True, channel="msedge")
            except Exception:
                launched = playwright.chromium.launch(
                    headless=True, executable_path=os.environ.get("PW_CHROMIUM_PATH") or None
                )
            try:
                yield launched
            finally:
                launched.close()
    except Exception as exc:
        pytest.skip(f"Local Chromium unavailable: {exc}")


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.route("**/*", lambda route: route.abort())
    try:
        yield page
    finally:
        page.close()


SHADOW_FORM = """
<div id="host"></div>
<script>
  const root = document.getElementById('host').attachShadow({mode: 'open'});
  root.innerHTML = `
    <label for="phone">Mobile phone</label>
    <input id="phone" type="tel" pattern="[0-9]{3}-[0-9]{3}-[0-9]{4}" value="(916) 555-0147">
    <label for="email">Email</label>
    <input id="email" type="email" value="z@quorvel.example">
    <label for="start">Available from</label>
    <input id="start" placeholder="MM/DD/YYYY" pattern="[0-9]{2}/[0-9]{2}/[0-9]{4}" value="2027-05-15">`;
</script>"""


def _rejected(page) -> dict[str, dict]:
    return {item["label"]: item for item in page_blockers.extract_page_blockers(page)["rejected"]}


def test_refused_answers_in_a_shadow_root_are_reported_apart_from_questions(page):
    page.set_content(SHADOW_FORM)
    info = page_blockers.extract_page_blockers(page)
    assert sorted(item["label"] for item in info["rejected"]) == ["Available from", "Mobile phone"]
    assert info["unresolved"] == []
    assert all("value" not in item and "current" not in item for item in info["rejected"])


def test_a_refused_phone_and_date_are_typed_again_in_the_forms_shape(page):
    page.set_content(SHADOW_FORM)
    found = _rejected(page)
    assert rejected_repair.repair(page, found["Mobile phone"])
    assert page.locator("#phone").input_value() == "916-555-0147"
    assert rejected_repair.repair(page, found["Available from"])
    assert page.locator("#start").input_value() == "05/15/2027"
    assert page.locator("#email").input_value() == "z@quorvel.example"  # accepted: untouched
    assert _rejected(page) == {}


def test_a_shape_nothing_fixes_is_put_back_and_noted(page):
    page.set_content('<label for="ref">Reference code</label>'
                     '<input id="ref" pattern="RT-[0-9]{4}" value="12345">')
    item = _rejected(page)["Reference code"]
    assert not rejected_repair.repair(page, item)
    assert page.locator("#ref").input_value() == "12345"
    assert rejected_repair.note_for(item).startswith("Reference code: ")


def test_a_refused_select_in_a_frame_becomes_a_review_note_without_the_model(page):
    page.set_content("""<iframe srcdoc='
      <div class="form-group"><label for="s">Work authorization</label>
      <select id="s" aria-invalid="true"><option>Citizen</option><option>Visa</option></select>
      <span class="field-error">Select a valid status</span></div>'></iframe>""")
    frame = page.frames[1]
    frame.wait_for_selector("#s")
    ledger = resolver_types.StepLedger()
    hybrid_resolver.resolve_step_blockers(
        frame, Packet.model_construct(fields={}), ApplicantProfile(), ledger=ledger,
    )
    assert ledger.review_notes == ["Work authorization: Select a valid status"]
    assert ledger.asked == set()  # never put to the model


@pytest.mark.parametrize(("item", "value", "expected"), [
    ({"label": "Phone", "kind": "tel"}, "9165550147",
     ["+19165550147", "(916) 555-0147", "916-555-0147", "+1 9165550147"]),
    ({"label": "Zip code", "kind": "text"}, "958141234", ["95814-1234", "95814"]),
    ({"label": "Start date", "kind": "text", "placeholder": "YYYY-MM-DD"}, "05/15/2027",
     ["2027-05-15", "05-15-2027", "15/05/2027", "05/15/27", "May 15, 2027"]),
    ({"label": "Why us?", "kind": "text"}, "Because", []),
])
def test_shapes_keep_the_value_and_change_only_its_form(item, value, expected):
    assert rejected_repair.shapes(item, value)[: len(expected)] == expected


def test_a_calling_code_menu_only_the_model_could_set_goes_to_it_only_when_refused(
    monkeypatch,
):
    """SmartRecruiters' code picker keeps its value in a shadow root no reader sees: the
    profile's code cannot be confirmed there, and the model would pick the same code."""
    monkeypatch.setattr(widget_actions, "_select_combobox_option", lambda *a, **k: False)
    resolver = hybrid_resolver._StepResolver(  # noqa: SLF001
        None, Packet.model_construct(fields={}), ApplicantProfile(), max_retries=1,
        on_progress=None, deadline=None, ledger=resolver_types.StepLedger(),
        only_invalid=False,
    )
    quiet = {"type": "combobox", "selector": "#code", "label": "Country code",
             "phone_code_menu": True, "invalid": False}
    refused = {**quiet, "selector": "#code2", "invalid": True}
    assert resolver._select_phone_codes([quiet, refused]) == [refused]  # noqa: SLF001


@pytest.mark.parametrize(("value", "known", "expected"), [
    ("05/06/2027", set(), []),  # May 6 or June 5: left as typed
    ("06/05/2027", {"2027-06-05"}, ["05/06/2027"]),  # the profile's date settles it
    ("25/06/2027", set(), ["06/25/2027"]),  # a day past 12 is unambiguous
])
def test_a_date_whose_day_and_month_could_swap_is_reshaped_only_when_settled(
    value, known, expected,
):
    item = {"label": "Start date", "kind": "text", "placeholder": "DD/MM/YYYY"}
    found = rejected_repair.shapes(item, value, known=known)
    assert found[:1] == expected


def test_a_retyped_answer_the_widget_empties_is_not_a_repair(page):
    page.set_content('<label for="d">Available from</label>'
                     '<input id="d" placeholder="MM/DD/YYYY" value="2027-05-15"'
                     ' pattern="[0-9]{2}/[0-9]{2}/[0-9]{4}">'
                     "<script>const d = document.getElementById('d');"
                     "d.addEventListener('change', () => { if (d.value !== '2027-05-15')"
                     " d.value = ''; });</script>")
    item = _rejected(page)["Available from"]
    assert not rejected_repair.repair(page, item)
    assert page.locator("#d").input_value() == "2027-05-15"


TWO_PHONES = """
<div id="home"></div><div id="work"></div>
<script>
  for (const [host, value] of [['home', '916-555-0147'], ['work', '(916) 555-0148']]) {
    document.getElementById(host).attachShadow({mode: 'open'}).innerHTML =
      `<label for="phone">${host} phone</label><input id="phone" type="tel"
        pattern="[0-9]{3}-[0-9]{3}-[0-9]{4}" value="${value}">`;
  }
</script>"""


def test_a_reused_id_in_another_shadow_root_is_repaired_in_its_own_root(page):
    page.set_content(TWO_PHONES)
    found = _rejected(page)
    assert list(found) == ["work phone"]
    assert found["work phone"]["selector"] == "#work >> #phone"
    assert rejected_repair.repair(page, found["work phone"])
    assert page.locator("#work >> #phone").input_value() == "916-555-0148"
    assert page.locator("#home >> #phone").input_value() == "916-555-0147"


def test_a_reused_id_no_host_tells_apart_is_noted_and_left(page):
    page.set_content(TWO_PHONES.replace('id="home"', 'class="home"').replace(
        'id="work"', 'class="work"').replace("getElementById(host)",
                                             "querySelector('.' + host)"))
    item = _rejected(page)["work phone"]
    assert item["ambiguous"] and item["selector"] == ""
    ledger = resolver_types.StepLedger()
    hybrid_resolver.resolve_step_blockers(
        page, Packet.model_construct(fields={}), ApplicantProfile(), ledger=ledger,
    )
    assert ledger.review_notes[0].startswith("work phone: ")
    assert page.locator(".home >> #phone").input_value() == "916-555-0147"
