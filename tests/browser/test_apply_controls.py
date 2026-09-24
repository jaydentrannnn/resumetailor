"""Offline browser checks for field identity and committed selections."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

from resume_tailor import config
from resume_tailor.apply import adapters, controls, scanner
from resume_tailor.apply import workday_auth
from resume_tailor.apply.profile import ApplicantProfile


pytestmark = pytest.mark.browser
_EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


async def _browser():
    assert _EDGE.is_file(), "Install Edge or provision a local Chromium test browser"
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
    return playwright, browser


def test_reacquires_field_after_sibling_is_inserted():
    async def run():
        playwright, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content('<form><input aria-label="Preferred First Name"><input aria-label="Last Name"></form>')
            observed = await scanner.scan(page)
            field = next(item for item in observed.fields if item.label == "Preferred First Name")
            await page.evaluate("document.querySelector('form').insertAdjacentHTML('afterbegin', '<input aria-label=Other>')")
            result = await controls.apply_value(page, observed, field, "Jayden")
            assert result.state == "verified_filled"
            assert await page.get_by_label("Preferred First Name").input_value() == "Jayden"
            assert await page.get_by_label("Other").input_value() == ""
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


def test_native_select_uses_unique_observed_option():
    async def run():
        playwright, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content('''
                <label for="degree">Degree</label>
                <select id="degree">
                    <option value="">Select degree</option>
                    <option value="bs">Bachelor of Science</option>
                    <option value="ba" disabled>Bachelor of Arts</option>
                </select>''')
            observed = await scanner.scan(page)
            field = next(item for item in observed.fields if item.label == "Degree")
            field.canonical_key = "degree_level"
            result = await controls.apply_value(page, observed, field, "Bachelor of Science")
            assert result.state == "verified_filled"
            assert await page.locator("#degree").input_value() == "bs"
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


def test_conditional_answer_is_observed_after_choice():
    async def run():
        playwright, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content('''
                <label for="hispanic">Are you Hispanic/Latino?</label>
                <select id="hispanic">
                  <option value="">Select an option</option>
                  <option value="no">No</option>
                  <option value="yes">Yes</option>
                </select>
                <div id="followup" hidden>
                  <label for="race">Race detail</label>
                  <select id="race">
                    <option value="">Select an option</option>
                    <option value="se-asia">Southeast Asian</option>
                    <option value="asia">Asian</option>
                  </select>
                </div>
                <script>
                  document.getElementById('hispanic').addEventListener('change', () => {
                    document.getElementById('followup').hidden = false;
                  });
                </script>''')
            before = await scanner.scan(page)
            assert [field.label for field in before.fields] == ["Are you Hispanic/Latino?"]
            question = before.fields[0]
            question.canonical_key = "hispanic_latino"
            outcome = await controls.apply_value(page, before, question, "No")
            assert outcome.state == "verified_filled"
            after = await scanner.scan(page)
            race = next(field for field in after.fields if field.label == "Race detail")
            race.canonical_key = "race"
            outcome = await controls.apply_value(page, after, race, "Southeast Asian")
            assert outcome.state == "verified_filled"
            assert await page.locator("#race").input_value() == "se-asia"
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


def test_portal_phone_dropdown_commits_united_states():
    async def run():
        playwright, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content('''
                <div class="form-group">
                  <label for="phone-country">Phone country code</label>
                  <div class="select__control">
                    <input id="phone-country" role="combobox" aria-controls="phone-menu" aria-expanded="false">
                    <span class="select__single-value"></span>
                  </div>
                </div>
                <div id="phone-menu" role="listbox" hidden>
                  <div role="option" data-value="US" aria-selected="false">United States (+1)</div>
                  <div role="option" data-value="CA" aria-selected="false">Canada (+1)</div>
                </div>
                <script>
                  const input = document.getElementById('phone-country');
                  const menu = document.getElementById('phone-menu');
                  const options = [...menu.querySelectorAll('[role=option]')];
                  input.addEventListener('click', () => { menu.hidden = false; input.setAttribute('aria-expanded', 'true'); });
                  input.addEventListener('keydown', event => {
                    if (event.key === 'Escape') { menu.hidden = true; input.setAttribute('aria-expanded', 'false'); }
                  });
                  input.addEventListener('input', () => {
                    options.forEach(option => { option.hidden = !option.textContent.toLowerCase().includes(input.value.toLowerCase()); });
                  });
                  options.forEach(option => option.addEventListener('click', () => {
                    options.forEach(item => item.setAttribute('aria-selected', String(item === option)));
                    document.querySelector('.select__single-value').textContent = '+1';
                    input.value = '';
                    menu.hidden = true;
                    input.setAttribute('aria-expanded', 'false');
                  }));
                </script>''')
            observed = await scanner.scan(page)
            field = next(item for item in observed.fields if item.label == "Phone country code")
            field.canonical_key = "phone_country_code"
            outcome = await controls.apply_value(page, observed, field, "+1", phone_region="United States")
            assert outcome.state == "verified_filled", outcome.reason_code
            assert await page.locator("[data-value=US]").get_attribute("aria-selected") == "true"
            assert await page.locator("[data-value=CA]").get_attribute("aria-selected") == "false"
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


def test_greenhouse_replacement_upload_remains_observable():
    async def run():
        playwright, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content('''
                <div class="file-upload" role="group">
                  <div class="label upload-label">Resume/CV*</div>
                  <div class="file-upload__filename"><p>Prepared Resume.pdf</p></div>
                </div>
                <div class="file-upload" role="group">
                  <div class="label upload-label">Cover Letter</div>
                  <div class="file-upload__filename"><p>Prepared Cover Letter.pdf</p></div>
                </div>''')
            observed = await scanner.scan(page)
            files = [item for item in observed.fields if item.control_kind == "file"]
            assert [(item.label, item.current_value) for item in files] == [
                ("Resume/CV*", "Prepared Resume.pdf"),
                ("Cover Letter", "Prepared Cover Letter.pdf"),
            ]
            assert files[0].required and not files[1].required
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


def test_greenhouse_education_suffixes_identify_distinct_rows():
    async def run():
        playwright, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content('''
                <input id="school--0" aria-label="School">
                <input id="school--1" aria-label="School">
                <input id="end-year--1" aria-label="End date year" type="number">''')
            observed = await scanner.scan(page)
            assert [(item.constraints["id"], item.repeater_row_id) for item in observed.fields] == [
                ("school--0", "0"), ("school--1", "1"), ("end-year--1", "1"),
            ]
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


def test_workday_honeypot_is_not_an_application_field():
    async def run():
        playwright, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content('''
                <input aria-label="Email Address" type="email">
                <input data-automation-id="beecatcher" aria-label="Enter website. This input is for robots only" type="text">''')
            observed = await scanner.scan(page)
            assert [item.label for item in observed.fields] == ["Email Address"]
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


#: Clicking Create Account records whether the terms box was ticked, then shows a signed-in form.
_SIGNED_IN_AFTER_SUBMIT = (
    "window.termsAtSubmit = document.querySelector('[data-automation-id=createAccountCheckbox]').checked;"
    "document.body.innerHTML = '<div data-automation-id=utilityButtonAccountTasksMenu>Account</div>"
    "<div data-automation-id=applyFlowPage>My Information</div>';"
)


def test_workday_create_account_ticks_account_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    assert _EDGE.is_file()
    html = f'''
        <h1>Create Account</h1>
        <input data-automation-id="email" type="email">
        <input data-automation-id="password" type="password" autocomplete="new-password">
        <input data-automation-id="verifyPassword" type="password" autocomplete="new-password">
        <label><input data-automation-id="createAccountCheckbox" type="checkbox">I agree to the terms</label>
        <button data-automation-id="createAccountSubmitButton" onclick="{_SIGNED_IN_AFTER_SUBMIT}">Create Account</button>'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
            page.goto("https://fixture.myworkdayjobs.com/job/1")
            assert workday_auth.detect_auth_state(page) == "create_account"
            outcome = workday_auth.handle_workday_auth(
                page, "fixture", ApplicantProfile(email="applicant@example.com"),
            )
            assert outcome == "authenticated"
            assert page.evaluate("window.termsAtSubmit") is True
        finally:
            browser.close()


def test_workday_terms_that_cannot_be_ticked_are_handed_over(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    html = '''
        <input data-automation-id="email" type="email">
        <input data-automation-id="password" type="password" autocomplete="new-password">
        <input data-automation-id="verifyPassword" type="password" autocomplete="new-password">
        <label><input data-automation-id="createAccountCheckbox" type="checkbox"
               onclick="event.preventDefault()">I agree to the terms</label>
        <button data-automation-id="createAccountSubmitButton" onclick="window.submitted=true">Create Account</button>'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
            page.goto("https://fixture.myworkdayjobs.com/job/1")
            outcome = workday_auth.handle_workday_auth(
                page, "fixture", ApplicantProfile(email="applicant@example.com"),
            )
            assert outcome == "terms_needed"
            assert page.evaluate("window.submitted === true") is False
        finally:
            browser.close()


def test_async_workday_entry_ticks_account_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)

    async def run():
        playwright, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.route("**/*", lambda route: route.fulfill(body=f'''
                <button id="apply" onclick="this.remove(); document.getElementById('manual').hidden=false">Apply</button>
                <button id="manual" hidden onclick="this.remove(); document.getElementById('account').hidden=false">Apply Manually</button>
                <div id="account" hidden>
                  <input data-automation-id="email" type="email">
                  <input data-automation-id="password" type="password" autocomplete="new-password">
                  <input data-automation-id="verifyPassword" type="password" autocomplete="new-password">
                  <label><input data-automation-id="createAccountCheckbox" type="checkbox">I agree to the terms</label>
                  <button data-automation-id="createAccountSubmitButton" onclick="{_SIGNED_IN_AFTER_SUBMIT}">Create Account</button>
                </div>''', content_type="text/html"))
            await page.goto("https://fixture.myworkdayjobs.com/job/1")
            await adapters.WorkdayAdapter().enter_application(page, timeout_ms=5000)
            assert await workday_auth.detect_auth_state_async(page) == "create_account"
            outcome = await workday_auth.handle_workday_auth_async(
                page, ApplicantProfile(email="applicant@example.com"), deadline=time.monotonic() + 20,
            )
            assert outcome == "authenticated"
            assert await page.evaluate("window.termsAtSubmit") is True
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


def test_workday_entry_tracks_single_popup_tab():
    async def run():
        playwright, browser = await _browser()
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.set_content('''
                <button onclick="window.open('about:blank', '_blank')">Apply</button>
                <script>
                  window.addEventListener('message', event => {
                    if (event.data === 'unused') throw new Error('unexpected');
                  });
                </script>''')
            resulting = await adapters.WorkdayAdapter().enter_application(page, timeout_ms=5000)
            assert resulting != page
            assert resulting in context.pages
            assert len(context.pages) == 2
        finally:
            await browser.close()
            await playwright.stop()

    asyncio.run(run())


_WORKDAY_MY_INFO = '''
    <div data-automation-id="utilityButtonAccountTasksMenu">me</div>
    <div data-automation-id="applyFlowPage"><ol data-automation-id="progressBar">
      <li data-automation-id="progressBarActiveStep">current step 1 of 6 My Information</li></ol>
      <div data-automation-id="applyFlowMyInfoPage"><div data-automation-id="formField-country"></div></div>
      <button data-automation-id="pageFooterNextButton">Save and Continue</button></div>'''
_SWAP_SCRIPT = f"<script>function swapToMyInfo() {{ document.body.innerHTML = {json.dumps(_WORKDAY_MY_INFO)}; }}</script>"


def test_workday_create_account_clicks_through_the_click_filter_overlay(tmp_path, monkeypatch):
    """Live Workday covers its submit button with a transparent overlay that eats clicks."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    html = f'''
        <div data-automation-id="utilityButtonSignIn">Sign In</div>
        <div data-automation-id="applyFlowPage">
          <input data-automation-id="email" type="text" aria-label="Email Address">
          <input data-automation-id="password" type="password">
          <input data-automation-id="verifyPassword" type="password">
          <input data-automation-id="beecatcher" type="text">
          <div style="position:relative;width:200px;height:40px">
            <button data-automation-id="createAccountSubmitButton" onclick="window.buttonClicked=true"
                    style="position:absolute;inset:0">Create Account</button>
            <div data-automation-id="click_filter" role="button" aria-label="Create Account"
                 style="position:absolute;inset:0;z-index:2"
                 onclick="swapToMyInfo()"></div>
          </div>
        </div>{_SWAP_SCRIPT}'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
            page.goto("https://fixture.wd5.myworkdayjobs.com/en-US/site/job/R1/apply/applyManually")
            outcome = workday_auth.handle_workday_auth(
                page, "fixture", ApplicantProfile(email="applicant@example.com"),
                deadline=time.monotonic() + 30,
            )
            assert outcome == "authenticated"
            assert page.evaluate("window.buttonClicked === true") is False
            assert workday_auth._load_vault()["fixture.wd5.myworkdayjobs.com"]["created"] is True  # noqa: SLF001
        finally:
            browser.close()


def test_workday_entry_goes_through_apply_manually_only():
    from resume_tailor.apply import workday_flow

    html = f'''
        <div data-automation-id="utilityButtonAccountTasksMenu">me</div>
        <div data-automation-id="jobPostingPage">
          <a data-automation-id="adventureButton" role="button" href="#" onclick="event.preventDefault();
             document.getElementById('dialog').hidden=false">Apply</a></div>
        <div id="dialog" role="dialog" aria-label="Start Your Application" hidden>
          <a data-automation-id="autofillWithResume" role="button" href="#" onclick="window.autofill=true">Autofill with Resume</a>
          <a data-automation-id="applyManually" role="button" href="#"
             onclick="event.preventDefault(); swapToMyInfo()">Apply Manually</a>
        </div>{_SWAP_SCRIPT}'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
            page.goto("https://fixture.wd5.myworkdayjobs.com/en-US/site/job/R1")
            resulting, state = workday_flow.enter_application(page, context, deadline=time.monotonic() + 30)
            assert resulting is page
            assert state == "apply_form"
            assert workday_flow.active_step(workday_flow.snapshot(page)) == "My Information"
            assert page.evaluate("window.autofill === true") is False
        finally:
            browser.close()


def test_workday_sign_in_overlay_found_by_position_not_label(tmp_path, monkeypatch):
    """AmFam's Sign In overlay is labelled "Submit" while the button says "Sign In"."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    workday_auth._save_vault({"fixture.wd1.myworkdayjobs.com": {  # noqa: SLF001
        "email": "applicant@example.com", "password": "Saved!Pass1", "created": True,
    }})
    html = f'''
        <div data-automation-id="utilityButtonSignIn">Sign In</div>
        <div data-automation-id="applyFlowPage"><div data-automation-id="signInContent">
          <button data-automation-id="SignInWithEmailButton"
                  onclick="document.getElementById('form').hidden=false; this.remove()">Sign in with email</button>
          <div id="form" hidden>
            <input data-automation-id="email" type="text"><input data-automation-id="password" type="password">
            <div style="position:relative;width:200px;height:40px">
              <button data-automation-id="signInSubmitButton" onclick="window.buttonClicked=true"
                      style="position:absolute;inset:0">Sign In</button>
              <div data-automation-id="click_filter" role="button" aria-label="Submit"
                   style="position:absolute;inset:0;z-index:2" onclick="swapToMyInfo()"></div>
            </div>
          </div></div></div>{_SWAP_SCRIPT}'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
            page.goto("https://fixture.wd1.myworkdayjobs.com/en-US/site/job/R2/apply/applyManually")
            outcome = workday_auth.handle_workday_auth(
                page, "fixture", ApplicantProfile(email="applicant@example.com"),
                deadline=time.monotonic() + 30,
            )
            assert outcome == "authenticated"
            assert page.evaluate("window.buttonClicked === true") is False
        finally:
            browser.close()


def test_workday_sign_in_waits_for_an_overlay_that_paints_late(tmp_path, monkeypatch):
    """Live 2026-09-23: the Sign In form painted before its click overlay, the tool clicked
    the handler-less bare button, and the run wrongly reported a rejected password."""
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    html = f'''
        <div data-automation-id="utilityButtonSignIn">Sign In</div>
        <div data-automation-id="applyFlowPage"><div data-automation-id="signInContent">
          <input data-automation-id="email" type="text"><input data-automation-id="password" type="password">
          <div id="slot" style="position:relative;width:200px;height:40px">
            <button data-automation-id="signInSubmitButton" onclick="window.bareClicks=(window.bareClicks||0)+1"
                    style="position:absolute;inset:0">Sign In</button>
          </div></div></div>{_SWAP_SCRIPT}
        <script>
          setTimeout(() => {{
            const o = document.createElement('div');
            o.setAttribute('data-automation-id', 'click_filter');
            o.setAttribute('role', 'button');
            o.setAttribute('aria-label', 'Sign In');
            o.style.cssText = 'position:absolute;inset:0;z-index:2';
            o.onclick = () => {{ window.overlayClicks = (window.overlayClicks || 0) + 1; setTimeout(swapToMyInfo, 300); }};
            document.getElementById('slot').appendChild(o);
          }}, 600);
        </script>'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
            page.goto("https://fixture.wd5.myworkdayjobs.com/en-US/site/job/R3/apply/applyManually")
            outcome = workday_auth.handle_workday_auth(
                page, "fixture",
                ApplicantProfile(email="applicant@example.com", workday_password="Mine!Pass9"),
                deadline=time.monotonic() + 30,
            )
            assert outcome == "authenticated"
            assert page.evaluate("window.overlayClicks") == 1
            assert page.evaluate("window.bareClicks || 0") == 0
        finally:
            browser.close()


#: Workday My Experience / My Information markup (captured 2026-09): an upload widget,
#: a multiselect prompt, and one real single-select dropdown.
_WORKDAY_STEP = '''
    <div data-automation-id="applyFlowPage">
      <h3>Resume/CV</h3>
      <div data-automation-id="file-upload-drop-zone">
        <button data-automation-id="select-files">Select files</button>
        <input data-automation-id="file-upload-input-ref" type="file" style="display:none">
      </div>
      <div data-automation-id="formField-source">
        <label>How Did You Hear About Us?*</label>
        <div data-automation-id="multiSelectContainer" id="ms1">
          <div data-automation-id="multiselectInputContainer">0 items selected
            <input id="source--source" role="combobox" placeholder="Search">
            <div data-automation-id="promptSelectionLabel"></div>
          </div>
        </div>
      </div>
      <div data-automation-id="formField-state">
        <label for="address--countryRegion">State*</label>
        <button id="address--countryRegion" aria-haspopup="listbox" aria-controls="st">Select One</button>
        <button id="address--countryRegion-icon" aria-haspopup="listbox" aria-label="State">Select One</button>
        <ul id="st" role="listbox" hidden><li role="option">California</li></ul>
      </div>
      <input data-automation-id="profileSectionFlag" type="hidden">
    </div>'''


def test_resolver_never_treats_upload_or_prompt_widgets_as_dropdowns(monkeypatch):
    from types import SimpleNamespace

    from resume_tailor.apply import hybrid_resolver
    from resume_tailor.apply.packet import Packet

    calls: list[dict] = []

    class _Messages:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(parsed_output=hybrid_resolver.StepResolution(actions=[]))

    monkeypatch.setattr(hybrid_resolver.llm, "client_for", lambda _purpose: SimpleNamespace(timeout=60.0, messages=_Messages()))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
        try:
            page = browser.new_page()
            page.set_content(_WORKDAY_STEP)
            choosers: list[object] = []
            page.on("filechooser", lambda chooser: choosers.append(chooser))
            info = hybrid_resolver.extract_page_blockers(page)
            assert [(f["selector"], f["label"]) for f in info["unresolved"]] == [("#address--countryRegion", "State*")]
            hybrid_resolver.resolve_step_blockers(
                page, Packet.model_construct(fields={}), ApplicantProfile(), max_retries=1,
                ledger=hybrid_resolver.StepLedger(),
            )
            assert choosers == []
            assert len(calls) == 1
            assert "select-files" not in calls[0]["messages"][0]["content"]
            assert hybrid_resolver._is_upload_widget(page.locator("[data-automation-id=select-files]"))  # noqa: SLF001
            assert not hybrid_resolver._is_upload_widget(page.locator("#address--countryRegion"))  # noqa: SLF001
        finally:
            browser.close()


#: A Workday Skills prompt: Enter searches (results stream in), a click adds a chip.
_SKILLS_PROMPT = '''
    <div data-automation-id="applyFlowPage">
      <div data-automation-id="formField-skills">
        <label for="skills--skills">Skills</label>
        <div data-automation-id="multiSelectContainer">
          <ul data-automation-id="selectedItemList" role="listbox">
            <li><div data-automation-id="selectedItem">SQL</div></li>
          </ul>
          <div data-automation-id="multiselectInputContainer">
            <input id="skills--skills" placeholder="Type to Add Skills">
          </div>
        </div>
      </div>
      <div id="popup"></div>
    </div>
    <script>
      const catalog = {
        "rag": ["Retrieval-Augmented Generation (RAG)", "Ragtime"],
        "data analysis": ["Data Analytics", "Data Analysis Tools"],
        "python": ["Python", "Python (Programming Language)"],
        "sql": ["SQL"],
        "cobol": [],
      };
      const box = document.getElementById("skills--skills");
      const popup = document.getElementById("popup");
      const list = document.querySelector("[data-automation-id=selectedItemList]");
      box.addEventListener("keydown", event => {
        if (event.key !== "Enter") return;
        popup.innerHTML = "";
        const found = catalog[box.value.toLowerCase()] || [];
        // Results arrive a little later, as on Workday.
        setTimeout(() => {
          if (!found.length) popup.innerHTML = '<div data-automation-id="promptOption">No Items.</div>';
          for (const text of found) {
            const option = document.createElement("div");
            option.setAttribute("data-automation-id", "promptOption");
            option.textContent = text;
            option.onclick = () => {
              list.insertAdjacentHTML("beforeend", `<li><div data-automation-id="selectedItem">${text}</div></li>`);
            };
            popup.appendChild(option);
          }
        }, 300);
      });
    </script>'''


def test_workday_skills_are_entered_one_at_a_time():
    from resume_tailor.apply import workday_flow

    asked: list[dict[str, list[str]]] = []

    def choose_many(unmatched):
        asked.append(unmatched)
        # A model pick outside the observed options is ignored.
        return {"data analysis": "Data Analytics", "Python Django": "Django"}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(_EDGE), headless=True)
        try:
            page = browser.new_page()
            page.set_content(_SKILLS_PROMPT)
            committed, review = workday_flow.fill_skills(
                page, ["RAG", "SQL", "data analysis", "COBOL", "Python"], choose_many=choose_many,
            )
            chips = page.locator("[data-automation-id=selectedItem]").all_inner_texts()
            assert chips == ["SQL", "Retrieval-Augmented Generation (RAG)", "Python", "Data Analytics"]
            assert [c["value"] for c in committed] == [
                "Retrieval-Augmented Generation (RAG)", "Python", "Data Analytics",
            ]
            # One model call, only for the skill whose search had options but no exact one.
            assert asked == [{"data analysis": ["Data Analytics", "Data Analysis Tools"]}]
            assert review == ["COBOL"]
        finally:
            browser.close()
