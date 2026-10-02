"""Accidental-submit guard: every Apply click goes through `apply/clicks.py`."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from resume_tailor.apply.driver import clicks

APPLY_DIR = Path(clicks.__file__).parent.parent


def test_no_raw_click_outside_clicks_module():
    offenders = []
    for path in sorted(APPLY_DIR.rglob("*.py")):
        if path.name == "clicks.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"click", "dblclick", "tap"}
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"route these through apply/clicks.py: {offenders}"


def test_only_fill_presses_submit():
    """Only the legacy fill's submit step (`fill_finish._dispatch_submit`) clicks submit."""
    users = [
        path.name
        for path in APPLY_DIR.rglob("*.py")
        if path.name != "clicks.py" and "submit_click(" in path.read_text(encoding="utf-8")
    ]
    assert users == ["fill_finish.py"]


class _Loc:
    """Stand-in for a Playwright locator: answers the two probes `clicks` evaluates."""

    def __init__(self, label: str = "", submit_control: bool = False, unreadable=False):
        self.label = label
        self.submit_control = submit_control
        self.unreadable = unreadable
        self.clicked = 0

    def evaluate(self, script, timeout=None):
        if self.unreadable:
            raise TimeoutError("detached")
        if "tagName" in script:
            return {"submitInput": self.submit_control, "buttonish": False, "label": self.label}
        return self.label

    def click(self, **_kwargs):
        self.clicked += 1


@pytest.mark.parametrize(
    "label",
    [
        "Submit",  # Workday Review step, iCIMS, Taleo, SuccessFactors
        "Submit Application",  # Greenhouse
        "Submit application",  # Lever, Ashby
        "Send application",
        "Review and Submit",
        "Finish",
    ],
)
@pytest.mark.parametrize("purpose", ["advance", "enter", "dismiss"])
def test_navigation_clicks_refuse_submits(label, purpose):
    loc = _Loc(label)
    with pytest.raises(clicks.SubmitRefused):
        clicks.safe_click(loc, purpose=purpose)
    assert loc.clicked == 0


@pytest.mark.parametrize("label", ["Next", "Continue", "Save and Continue", "Apply", "Apply Manually"])
def test_navigation_clicks_allow_advances(label):
    loc = _Loc(label)
    clicks.safe_click(loc, purpose="advance")
    assert loc.clicked == 1


def test_unreadable_button_is_treated_as_submit():
    with pytest.raises(clicks.SubmitRefused):
        clicks.safe_click(_Loc(unreadable=True), purpose="advance")


def test_select_refuses_real_submit_controls_only():
    clicks.safe_click(_Loc("Complete"), purpose="select")  # an option may say anything
    with pytest.raises(clicks.SubmitRefused):
        clicks.safe_click(_Loc("Submit", submit_control=True), purpose="select")


def test_auth_clicks_are_not_text_checked():
    loc = _Loc("Submit")  # Workday's sign-in overlay is labelled "Submit" on some tenants
    clicks.safe_click(loc, purpose="auth")
    assert loc.clicked == 1


def test_submit_click_needs_an_auto_submit_decision():
    loc = _Loc("Submit Application")
    with pytest.raises(clicks.SubmitRefused):
        clicks.submit_click(loc, decision="awaiting_review")
    clicks.submit_click(loc, decision="auto_submit")
    assert loc.clicked == 1


class _Mouse:
    def __init__(self):
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))


class _Page:
    def __init__(self, label):
        self.label = label
        self.mouse = _Mouse()

    def evaluate(self, _script, _arg):
        return self.label


def test_mouse_click_checks_the_element_under_the_point():
    page = _Page("Submit")
    with pytest.raises(clicks.SubmitRefused):
        clicks.mouse_click(page, 1, 2, purpose="dismiss")
    clicks.mouse_click(page, 1, 2, purpose="auth")
    assert page.mouse.clicks == [(1, 2)]


async def test_async_variants_match():
    class _AsyncLoc(_Loc):
        async def evaluate(self, script, timeout=None):
            return _Loc.evaluate(self, script, timeout)

        async def click(self, **_kwargs):
            self.clicked += 1

    with pytest.raises(clicks.SubmitRefused):
        await clicks.async_safe_click(_AsyncLoc("Submit"), purpose="advance")
    loc = _AsyncLoc("Next")
    await clicks.async_safe_click(loc, purpose="advance")
    assert loc.clicked == 1


_PAGES = {
    "workday_review": """<div data-automation-id="pageFooter">
        <button data-automation-id="pageFooterNextButton">Submit</button></div>""",
    "greenhouse_final": """<form action="/applications/submit">
        <button type="submit" id="submit_app">Submit Application</button></form>""",
    "icims_submit": """<form><input type="submit" value="Submit" class="iCIMS_Button"></form>""",
}


@pytest.mark.parametrize("name", sorted(_PAGES))
def test_real_dom_submit_buttons_are_refused(name):
    """Against a real Chromium DOM, when one is available."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Local Chromium unavailable: {exc}")
        try:
            page = browser.new_page()
            page.set_content(_PAGES[name])
            target = page.locator("button, input[type=submit]").first
            with pytest.raises(clicks.SubmitRefused):
                clicks.safe_click(target, purpose="advance", timeout=1000)
            with pytest.raises(clicks.SubmitRefused):
                clicks.safe_click(target, purpose="select", timeout=1000)
        finally:
            browser.close()
