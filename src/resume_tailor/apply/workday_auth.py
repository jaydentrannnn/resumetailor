"""Workday account management and authentication automation over CDP.

Handles Workday's per-tenant account requirement (Sign In vs Create Account),
password complexity constraints, and email verification OTP pause/resume.
"""

from __future__ import annotations

import contextlib
import json
import re
import secrets
import string
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from resume_tailor import config
from resume_tailor.apply import store
from resume_tailor.apply.profile import ApplicantProfile

_VAULT_FILENAME = "workday_vault.json"


def _vault_path() -> Path:
    """Return path to the local Workday credential vault."""
    config.APPLICATIONS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return config.APPLICATIONS_OUTPUT_DIR / _VAULT_FILENAME


def _load_vault() -> dict[str, dict[str, str]]:
    """Load cached tenant credentials, or return empty dict."""
    path = _vault_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_vault(vault: dict[str, dict[str, str]]) -> None:
    """Persist tenant credentials atomically."""
    path = _vault_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(vault, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def extract_workday_tenant(url: str) -> str:
    """Derive tenant identifier from Workday URL (e.g. 'nvidia.myworkdayjobs.com')."""
    hostname = urlparse(url).hostname or ""
    return hostname.lower()


def generate_compliant_password(base_seed: str = "ResumeTailor") -> str:
    """Generate a password meeting Workday requirements (>=8 chars, upper, lower, digit, special)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    random_tail = "".join(secrets.choice(alphabet) for _ in range(14))
    return f"Rt!7{random_tail}"


def get_tenant_credentials(
    url: str,
    profile: ApplicantProfile,
) -> tuple[str, str]:
    """Return (email, password) for the given Workday URL from profile or vault."""
    tenant = extract_workday_tenant(url)
    vault = _load_vault()

    email = (getattr(profile, "workday_email", None) or profile.email or "").strip()
    if not email:
        raise ValueError("Applicant email is required for Workday authentication")

    password = (getattr(profile, "workday_password", None) or "").strip()
    if not password:
        if tenant in vault and vault[tenant].get("password"):
            password = vault[tenant]["password"]
        else:
            password = generate_compliant_password()

    vault[tenant] = {**vault.get(tenant, {}), "email": email, "password": password}
    _save_vault(vault)
    return email, password


def is_workday_url(url: str) -> bool:
    """True if URL matches Workday domain patterns."""
    lowered = url.lower()
    return "myworkdayjobs.com" in lowered or "workday.com" in lowered


def detect_auth_state(page: Any) -> Literal["none", "sign_in", "create_account", "otp", "logged_in"]:
    """Detect the current Workday authentication screen state."""
    # 1. Check for OTP / Verification Code screen
    otp_selectors = [
        "input[data-automation-id='verificationCode']",
        "input[data-automation-id='securityCode']",
        "input[name*='verificationCode' i]",
        "input[autocomplete='one-time-code']",
    ]
    for sel in otp_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return "otp"
        except Exception:  # noqa: BLE001
            pass

    # 2. Confirm account creation from form fields, not navigation links.
    create_selectors = [
        "input[data-automation-id='verifyPassword']",
        "input[autocomplete='new-password']",
    ]
    for sel in create_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return "create_account"
        except Exception:  # noqa: BLE001
            pass

    # 3. Check for Sign In form
    signin_selectors = [
        "input[data-automation-id='password']",
        "input[autocomplete='current-password']",
    ]
    for sel in signin_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return "sign_in"
        except Exception:  # noqa: BLE001
            pass

    # 4. Check if Create Account / Sign In links exist on modal
    try:
        calink = page.locator("[data-automation-id='createAccountLink'], button:has-text('Create Account')").first
        if calink.count() > 0 and calink.is_visible():
            return "sign_in"
    except Exception:  # noqa: BLE001
        pass

    return "none"


#: Visible markers that only exist inside a signed-in Workday session or its apply flow.
#: (`applyFlowPage` alone is not enough: the Create Account/Sign In step lives inside it.)
_SIGNED_IN_SELECTORS = (
    "[data-automation-id='utilityButtonAccountTasksMenu']",
    "[data-automation-id='applyFlowMyInfoPage']",
    "[data-automation-id='applyFlowMyExpPage']",
    "[data-automation-id='pageFooterNextButton']",
    "[data-automation-id='signOut']",
)


def _authenticated_evidence(page: Any) -> bool:
    """Require visible signed-in/application UI before treating a vanished form as success."""
    for selector in _SIGNED_IN_SELECTORS:
        try:
            target = page.locator(selector).first
            if target.count() > 0 and target.is_visible():
                return True
        except Exception:  # noqa: BLE001 - failed inspection is not success
            continue
    return False


AuthResult = Literal[
    "authenticated", "verification_needed", "credentials_needed", "sign_in_failed",
    "account_exists_other_password", "terms_needed", "no_response", "failed",
]

#: Human handoff text for every non-authenticated outcome (shown on the Applications row).
AUTH_HANDOFF: dict[str, str] = {
    "verification_needed": "Workday sent a verification email or code. Verify it in this tab, then Continue fill.",
    "credentials_needed": "Add an applicant email before continuing Workday authentication.",
    "sign_in_failed": "Workday did not accept the saved email and password on this site. "
    "Sign in in this tab (or update your Workday password in the applicant profile), then Continue fill.",
    "account_exists_other_password": "This Workday site already has an account for your email, under a "
    "different password. Use Forgot Password (or sign in) in this tab, then Continue fill.",
    "terms_needed": "Workday's account terms could not be ticked automatically. Accept them in this tab, "
    "then Continue fill.",
    "no_response": "Workday didn't respond to the Sign In / Create Account button. "
    "Click it in this tab, then Continue fill.",
    "failed": "Workday sign-in could not be completed automatically; finish it in this tab, then Continue fill.",
}

_EXISTS = re.compile(r"already (?:exists|in use|registered)|already have an account", re.I)


def _mark_created(tenant: str) -> None:
    vault = _load_vault()
    vault.setdefault(tenant, {})["created"] = True
    _save_vault(vault)


def _mark_signed_in(tenant: str) -> None:
    vault = _load_vault()
    vault.setdefault(tenant, {})["signed_in"] = True
    _save_vault(vault)


def _known_site(tenant: str) -> bool:
    """This tool has created an account on, or signed in to, this Workday site before."""
    entry = _load_vault().get(tenant, {})
    return bool(entry.get("created") or entry.get("signed_in"))


def _fill(page: Any, automation_id: str, value: str) -> None:
    page.locator(f"input[data-automation-id='{automation_id}']").first.fill(value, timeout=5000)


_TERMS = "input[data-automation-id='createAccountCheckbox']"


def _accept_account_terms(page: Any) -> bool | None:
    """Tick Create Account's terms box; None when there is none to tick.

    Only the account-creation terms: consent boxes inside the application itself are
    still left to the applicant. A box that will not report checked is a handoff.
    """
    terms = page.locator(_TERMS).first
    if not (terms.count() > 0 and terms.is_visible()):
        return None
    if terms.is_checked():
        return True
    with contextlib.suppress(Exception):
        terms.check(timeout=3000)
    if not terms.is_checked():
        # A styled checkbox: its label takes the click.
        box_id = terms.get_attribute("id") or ""
        label = page.locator(f"label[for='{box_id}']") if box_id else None
        with contextlib.suppress(Exception):
            if label is not None and label.count():
                label.first.click(timeout=3000)
            else:
                terms.click(timeout=3000, force=True)
    return bool(terms.is_checked())


async def _accept_account_terms_async(page: Any, *, timeout_ms: int) -> bool | None:
    terms = page.locator(_TERMS).first
    if not (await terms.count() and await terms.is_visible()):
        return None
    if await terms.is_checked():
        return True
    with contextlib.suppress(Exception):
        await terms.check(timeout=timeout_ms)
    if not await terms.is_checked():
        box_id = await terms.get_attribute("id") or ""
        with contextlib.suppress(Exception):
            label = page.locator(f"label[for='{box_id}']")
            if box_id and await label.count():
                await label.first.click(timeout=timeout_ms)
            else:
                await terms.click(timeout=timeout_ms, force=True)
    return bool(await terms.is_checked())


def _alerts(snap: dict[str, Any]) -> str:
    return "; ".join(snap.get("alerts") or [])


#: How long a submit may show no sign of life before it is clicked once more.
_RESPONSE_WINDOW_S = 4.0


_BUSY_ID = re.compile(r"load|spinner|busy", re.I)


def _fingerprint(snap: dict[str, Any]) -> tuple[Any, ...]:
    """What a submit visibly changes: URL, messages, loading markers.

    Focus decorations (``focus-ring``) come and go with any click, and the click overlay
    itself may still be painting, so neither counts as Workday reacting.
    """
    ids = set(snap.get("ids") or [])
    return (
        snap.get("url"),
        tuple(snap.get("alerts") or []),
        tuple(sorted(i for i in ids if _BUSY_ID.search(i))),
    )


def _submit(
    page: Any,
    submit_id: str,
    inputs: tuple[str, ...],
    form_state: str,
    done: set[str],
    *,
    stop: float,
    log: Callable[[str], None],
) -> tuple[str, dict[str, Any]]:
    """Click an auth form's submit and make sure Workday reacted to it.

    A click on the bare button (no overlay yet) is silently ignored by Workday, so a submit
    that sends nothing and leaves the page exactly as it was for a few seconds is clicked
    once more. A click that did send a request is never repeated, however slowly Workday
    answers (live sign-in rejections took ~20s): a second wrong-password attempt counts
    toward the account lockout. Returns the settled state and its snapshot.
    """
    from resume_tailor.apply import workday_flow

    posted: list[str] = []

    def _seen(request: Any) -> None:
        with contextlib.suppress(Exception):
            if request.method == "POST":
                posted.append(str(request.url))

    listen = getattr(page, "on", None)
    if callable(listen):
        listen("request", _seen)
    try:
        before = _fingerprint(workday_flow.snapshot(page))
        for attempt in (1, 2):
            posted.clear()
            method = workday_flow.click_control(page, submit_id, expect_overlay=True)
            log(f"clicked {submit_id} via {method or 'nothing (control missing)'}")
            window = min(stop, time.monotonic() + _RESPONSE_WINDOW_S)
            snap = workday_flow.snapshot(page)
            while (
                workday_flow.classify(snap) == form_state
                and _fingerprint(snap) == before
                and not posted
                and time.monotonic() < window
            ):
                page.wait_for_timeout(250)
                snap = workday_flow.snapshot(page)
            if posted:
                log("Workday received the submit; waiting for its answer")
                break
            if workday_flow.classify(snap) != form_state or _fingerprint(snap) != before:
                break
            if attempt == 1:
                log(f"Workday didn't react to {submit_id}; re-checking the form and clicking again")
                workday_flow.wait_for_auth_form_ready(page, submit_id, inputs, deadline=stop, timeout_s=4)
    finally:
        unlisten = getattr(page, "remove_listener", None)
        if callable(listen) and callable(unlisten):
            with contextlib.suppress(Exception):
                unlisten("request", _seen)
    state = workday_flow.wait_for_state(page, done, timeout_s=30, deadline=stop)
    return state, workday_flow.snapshot(page)


def _await_verification(source_job_id: str) -> None:
    app = store.get(source_job_id)
    if app:
        prompt_msg = AUTH_HANDOFF["verification_needed"]
        app.otp_prompt = prompt_msg
        store.set_status(app, "awaiting_otp", note=prompt_msg)
        store.upsert(app)


def handle_workday_auth(
    page: Any,
    source_job_id: str,
    profile: ApplicantProfile,
    *,
    on_progress: Callable[[str], None] | None = None,
    deadline: float | None = None,
) -> AuthResult:
    """Get a Workday tab past Create Account / Sign In, or hand it over with a reason.

    An existing browser session wins outright (no credentials touched). A site this tool
    has used before signs in. A new site creates an account first (with the profile
    password, else a generated one kept in the vault): Workday accounts are per site, and
    creating never spends a wrong-password attempt toward the lockout. When the account
    already exists, the profile password gets exactly one Sign In; a generated password is
    never tried against an account it did not create.
    """
    from resume_tailor.apply import workday_flow

    def log(msg: str) -> None:
        if on_progress:
            on_progress(f"[workday-auth] {msg}")

    if not is_workday_url(str(page.url)):
        return "authenticated"
    stop = deadline if deadline is not None else time.monotonic() + 60

    settled = {
        "apply_form", "auth_chooser", "sign_in", "create_account", "otp", "verify_email",
        "posting", "start_dialog",
    }
    state = workday_flow.wait_for_state(page, settled, timeout_s=15, deadline=stop)
    snap = workday_flow.snapshot(page)
    log(f"detected state: {state}")
    if state == "auth_chooser":
        # Email only: Google / LinkedIn sign-in would hand the applicant's identity to a
        # third-party login this tool cannot see or verify.
        log("choosing Sign in with email")
        workday_flow.click_control(page, "SignInWithEmailButton")
        state = workday_flow.wait_for_state(
            page, {"sign_in", "create_account", "apply_form", "otp"}, timeout_s=10, deadline=stop,
        )
        snap = workday_flow.snapshot(page)

    if state in {"otp", "verify_email"}:
        _await_verification(source_job_id)
        return "verification_needed"
    if state == "apply_form" or workday_flow.signed_in(snap):
        return "authenticated"
    if state not in {"sign_in", "create_account"}:
        return "failed"
    if not (profile.workday_email or profile.email):
        log("Applicant email is missing")
        return "credentials_needed"

    url = str(page.url)
    tenant = extract_workday_tenant(url)
    known = _known_site(tenant)
    profile_password = bool((profile.workday_password or "").strip())
    email, password = get_tenant_credentials(url, profile)
    exists = False

    try:
        if state == "sign_in" and not known:
            log("first visit to this Workday site; switching to Create Account")
            workday_flow.click_control(page, "createAccountLink")
            state = workday_flow.wait_for_state(page, {"create_account"}, timeout_s=8, deadline=stop)
        elif state == "create_account" and known:
            log("this Workday site was used before; switching to Sign In")
            workday_flow.click_control(page, "signInLink")
            state = workday_flow.wait_for_state(page, {"sign_in"}, timeout_s=8, deadline=stop)

        if state == "create_account":
            inputs = ("email", "password", "verifyPassword")
            top = workday_flow.wait_for_auth_form_ready(page, "createAccountSubmitButton", inputs, deadline=stop)
            log(f"filling Create Account (submit covered by: {top or 'not ready'})")
            _fill(page, "email", email)
            _fill(page, "password", password)
            _fill(page, "verifyPassword", password)
            accepted = _accept_account_terms(page)
            if accepted is False:
                log("Account terms could not be ticked; they need manual acceptance in the Workday tab")
                return "terms_needed"
            if accepted:
                log("accepted the Workday account terms")
            state, snap = _submit(
                page, "createAccountSubmitButton", inputs, "create_account",
                {"apply_form", "otp", "verify_email", "sign_in"}, stop=stop, log=log,
            )
            if _EXISTS.search(_alerts(snap)):
                log("an account already exists for this email on this site")
                if not profile_password:
                    return "account_exists_other_password"
                exists = True
                workday_flow.click_control(page, "signInLink")
                state = workday_flow.wait_for_state(page, {"sign_in"}, timeout_s=8, deadline=stop)
            elif state in {"apply_form", "otp", "verify_email", "sign_in"}:
                _mark_created(tenant)
                have_password = True
            if state in {"otp", "verify_email"}:
                _await_verification(source_job_id)
                return "verification_needed"
            if state == "apply_form" or workday_flow.signed_in(snap):
                return "authenticated"
            if state == "create_account":
                if not _alerts(snap):
                    log("Create Account did not respond")
                    return "no_response"
                log(f"Create Account did not complete: {_alerts(snap)}")
                return "failed"

        if state == "sign_in":
            if not (known or profile_password):
                return "sign_in_failed"
            inputs = ("email", "password")
            top = workday_flow.wait_for_auth_form_ready(page, "signInSubmitButton", inputs, deadline=stop)
            log(f"filling Sign In (submit covered by: {top or 'not ready'})")
            _fill(page, "email", email)
            _fill(page, "password", password)
            state, snap = _submit(
                page, "signInSubmitButton", inputs, "sign_in",
                {"apply_form", "otp", "verify_email"}, stop=stop, log=log,
            )
            if state in {"otp", "verify_email"}:
                _await_verification(source_job_id)
                return "verification_needed"
            if state == "apply_form" or workday_flow.signed_in(snap):
                _mark_signed_in(tenant)
                return "authenticated"
            if not _alerts(snap):
                # Still on the form with no error: the click never reached Workday. That is
                # not evidence about the password.
                log(f"Sign In did not respond (screen: {state})")
                return "no_response"
            log(f"Sign In was rejected: {_alerts(snap)}")
            return "account_exists_other_password" if exists else "sign_in_failed"
    except Exception as exc:  # noqa: BLE001 - a broken control becomes a handoff, not a crash
        log(f"authentication error: {type(exc).__name__}: {exc}")
        return "failed"
    return "failed"


async def _async_visible(page: Any, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        try:
            target = page.locator(selector).first
            if await target.count() and await target.is_visible():
                return True
        except Exception:  # noqa: BLE001 - lack of evidence is not success
            continue
    return False


async def detect_auth_state_async(page: Any) -> str:
    if await _async_visible(page, (
        "input[data-automation-id='verificationCode']",
        "input[data-automation-id='securityCode']",
        "input[autocomplete='one-time-code']",
    )):
        return "otp"
    if await _async_visible(page, (
        "input[data-automation-id='verifyPassword']",
        "input[autocomplete='new-password']",
    )):
        return "create_account"
    if await _async_visible(page, (
        "input[data-automation-id='password']",
        "input[autocomplete='current-password']",
    )):
        return "sign_in"
    return "none"


async def _authenticated_evidence_async(page: Any) -> bool:
    return await _async_visible(page, _SIGNED_IN_SELECTORS)


async def handle_workday_auth_async(
    page: Any, profile: ApplicantProfile, *, deadline: float,
) -> Literal["authenticated", "verification_needed", "credentials_needed", "terms_needed", "failed"]:
    """Bounded async Workday authentication with immediate manual handoff."""
    if not is_workday_url(str(page.url)):
        return "authenticated"

    def remaining() -> int:
        left = int((deadline - time.monotonic()) * 1000)
        if left <= 0:
            raise TimeoutError("Workday authentication reached the application deadline")
        return min(5000, left)

    state = await detect_auth_state_async(page)
    if state == "none":
        return "authenticated" if await _authenticated_evidence_async(page) else "failed"
    if state == "otp":
        return "verification_needed"
    if not (profile.workday_email or profile.email):
        return "credentials_needed"

    tenant = extract_workday_tenant(str(page.url))
    prior = _load_vault().get(tenant, {})
    email, password = get_tenant_credentials(str(page.url), profile)
    if state == "sign_in" and not prior.get("created"):
        link = page.locator(
            "[data-automation-id='createAccountLink'], "
            "button:has-text('Create Account'), a:has-text('Create Account')"
        ).first
        if await link.count() and await link.is_visible():
            await link.click(timeout=remaining())
            state = await detect_auth_state_async(page)

    if state == "create_account":
        await page.locator("input[data-automation-id='email'], input[type='email']").first.fill(email, timeout=remaining())
        await page.locator("input[data-automation-id='password']").first.fill(password, timeout=remaining())
        await page.locator("input[data-automation-id='verifyPassword']").first.fill(password, timeout=remaining())
        if await _accept_account_terms_async(page, timeout_ms=remaining()) is False:
            return "terms_needed"
        await page.locator(
            "button[data-automation-id='createAccountSubmitButton'], button:has-text('Create Account')"
        ).first.click(timeout=remaining())
        await page.wait_for_timeout(min(1000, remaining()))
        if await detect_auth_state_async(page) == "none" and await _authenticated_evidence_async(page):
            vault = _load_vault()
            vault.setdefault(tenant, {})["created"] = True
            _save_vault(vault)
            return "authenticated"
        body = (await page.locator("body").inner_text(timeout=remaining())).casefold()
        if "already exists" in body or "already have an account" in body:
            link = page.locator(
                "[data-automation-id='signInLink'], a:has-text('Sign In'), button:has-text('Sign In')"
            ).first
            if await link.count() and await link.is_visible():
                await link.click(timeout=remaining())
                state = "sign_in"
    if state == "sign_in":
        await page.locator("input[data-automation-id='email'], input[type='email']").first.fill(email, timeout=remaining())
        await page.locator("input[data-automation-id='password']").first.fill(password, timeout=remaining())
        await page.locator(
            "button[data-automation-id='signInSubmitButton'], "
            "button[data-automation-id='loginButton'], button:has-text('Sign In')"
        ).first.click(timeout=remaining())
        await page.wait_for_timeout(min(1000, remaining()))
    if await detect_auth_state_async(page) == "otp":
        return "verification_needed"
    return "authenticated" if await _authenticated_evidence_async(page) else "failed"
