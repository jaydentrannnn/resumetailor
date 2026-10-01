"""Deterministic email-route and Workday consent actions for both fill engines."""

from __future__ import annotations

import json
import re
import time
from typing import Any

_EMAIL_CHOICES = (
    re.compile(r"^(?:sign in|log in|login|continue) with (?:your )?email(?: address)?$", re.I),
    re.compile(r"^(?:create (?:an? )?account|sign up|register) with (?:your )?email(?: address)?$", re.I),
)
_SOCIAL = re.compile(r"google|gmail|linkedin|apple|facebook|microsoft|sso", re.I)

EMAIL_ROUTES_JS = r"""() => {
  const visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  const controls = [...document.querySelectorAll('button, a, [role="button"]')];
  return {
    password: [...document.querySelectorAll('input[type="password"]')].some(visible),
    email: [...document.querySelectorAll('input[type="email"]')].some(visible),
    choices: controls.map((el, index) => ({index, label: (el.getAttribute('aria-label') || el.innerText || '').trim(),
      marker: el.getAttribute('data-automation-id') || '', available: visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true',
      authPanel: !!el.closest('[role="dialog"], [id*="auth" i], [class*="auth" i], [data-automation-id="signInContent"]')})),
  };
}"""


def email_choice(snapshot: dict[str, Any]) -> int | None:
    """Pick one explicit email route; ambiguity is a handoff."""
    if snapshot.get("password"):
        return None
    choices = snapshot.get("choices") or []
    for pattern in _EMAIL_CHOICES:
        matches = [item for item in choices if item.get("available") and not _SOCIAL.search(str(item.get("label") or ""))
                   and (pattern.fullmatch(str(item.get("label") or "").strip())
                        or (pattern is _EMAIL_CHOICES[0] and item.get("marker") == "SignInWithEmailButton"))]
        if matches:
            return int(matches[0]["index"]) if len(matches) == 1 else None
    generic = [item for item in choices if item.get("available") and item.get("authPanel")
               and re.fullmatch(r"sign in|log in|create account|sign up", str(item.get("label") or "").strip(), re.I)]
    if len(generic) == 1:
        return int(generic[0]["index"])
    return None


def has_email_chooser(snapshot: dict[str, Any]) -> bool:
    return not snapshot.get("password") and any(
        any(pattern.fullmatch(str(item.get("label") or "").strip()) for pattern in _EMAIL_CHOICES)
        or item.get("marker") == "SignInWithEmailButton"
        or item.get("available") and item.get("authPanel") and
        bool(re.fullmatch(r"sign in|log in|create account|sign up", str(item.get("label") or "").strip(), re.I))
        for item in snapshot.get("choices") or []
    )


def social_only_chooser(snapshot: dict[str, Any]) -> bool:
    return not snapshot.get("password") and not has_email_chooser(snapshot) and any(
        item.get("available") and item.get("authPanel") and _SOCIAL.search(str(item.get("label") or ""))
        for item in snapshot.get("choices") or []
    )


def choose_email_sync(page: Any, *, deadline: float) -> str:
    """Return absent/selected/ambiguous/unchanged; select at most one route."""
    before = page.evaluate(EMAIL_ROUTES_JS)
    if not has_email_chooser(before):
        return "unavailable" if social_only_chooser(before) else "absent"
    index = email_choice(before)
    if index is None:
        return "ambiguous"
    if time.monotonic() >= deadline:
        return "unchanged"
    clicks.safe_click(page.locator("button, a, [role='button']").nth(index), purpose="auth", timeout=min(5000, max(1, int((deadline - time.monotonic()) * 1000))))
    for _ in range(12):
        after = page.evaluate(EMAIL_ROUTES_JS)
        if after != before:
            return "selected"
        page.wait_for_timeout(250)
    return "unchanged"


async def choose_email_async(page: Any, *, deadline: float) -> str:
    before = await page.evaluate(EMAIL_ROUTES_JS)
    if not has_email_chooser(before):
        return "unavailable" if social_only_chooser(before) else "absent"
    index = email_choice(before)
    if index is None:
        return "ambiguous"
    if time.monotonic() >= deadline:
        return "unchanged"
    await clicks.async_safe_click(page.locator("button, a, [role='button']").nth(index), purpose="auth", timeout=min(5000, max(1, int((deadline - time.monotonic()) * 1000))))
    for _ in range(12):
        after = await page.evaluate(EMAIL_ROUTES_JS)
        if after != before:
            return "selected"
        await page.wait_for_timeout(250)
    return "unchanged"


CONSENT_JS = r"""() => [...document.querySelectorAll('input[type="checkbox"]')].map((el, index) => {
  const box = el.closest('[data-automation-id^="formField-"], fieldset, .form-group') || el.parentElement;
  const labels = [...(el.labels || [])].map(node => node.innerText || node.textContent || '');
  const copy = labels.join(' ').trim() || (box?.querySelector('legend, label, [class*="description" i]')?.textContent || '').trim();
  const validation = !!box?.querySelector('[role="alert"], [aria-invalid="true"], [data-automation-id="errorMessage"]');
  const marker = !!box?.querySelector('[aria-required="true"], [class*="required" i]');
  return {index, id: el.id || '', label: copy, required: el.required || el.getAttribute('aria-required') === 'true' || validation || marker,
    checked: el.checked, enabled: !el.disabled, visible: !!(el.getClientRects().length || (el.labels?.[0]?.getClientRects().length))};
})"""

_CONSENT = re.compile(r"consent|privacy|personal data|data processing|terms|agree|accurate|certif|attest", re.I)
_EXCLUDE = re.compile(r"marketing|job alert|talent community|newsletter|background check|arbitration|signature", re.I)


def consent_candidates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    accepted = []
    unresolved = []
    for row in rows:
        label = str(row.get("label") or "").strip()
        if not row.get("required") or _EXCLUDE.search(label):
            continue
        if not label:
            unresolved.append(row)
            continue
        if _CONSENT.search(label):
            (accepted if row.get("enabled") and row.get("visible") else unresolved).append(row)
        elif re.search(r"acknowledge|understand|authorize|declaration", label, re.I):
            unresolved.append(row)
    return accepted, [str(row.get("label") or "Consent") for row in unresolved]


def accept_workday_sync(page: Any) -> tuple[list[dict[str, str]], list[str]]:
    rows, unresolved = consent_candidates(page.evaluate(CONSENT_JS))
    completed = []
    for row in rows:
        box = page.locator('input[type="checkbox"]').nth(row["index"])
        try:
            if not box.is_checked():
                try:
                    box.check(timeout=3000)
                except Exception:
                    box_id = box.get_attribute("id")
                    label = page.locator(f"label[for={json.dumps(box_id)}]") if box_id else box.locator("xpath=ancestor::label")
                    if label.count() != 1:
                        raise
                    clicks.safe_click(label, purpose="select", timeout=3000)
            if box.is_checked():
                completed.append({"label": row["label"], "id": row["id"], "value": "checked", "key": "workday_consent"})
            else:
                unresolved.append(row["label"])
        except Exception:
            unresolved.append(row["label"])
    return completed, unresolved


async def accept_workday_async(page: Any) -> tuple[list[dict[str, str]], list[str]]:
    rows, unresolved = consent_candidates(await page.evaluate(CONSENT_JS))
    completed = []
    for row in rows:
        box = page.locator('input[type="checkbox"]').nth(row["index"])
        try:
            if not await box.is_checked():
                try:
                    await box.check(timeout=3000)
                except Exception:
                    box_id = await box.get_attribute("id")
                    label = page.locator(f"label[for={json.dumps(box_id)}]") if box_id else box.locator("xpath=ancestor::label")
                    if await label.count() != 1:
                        raise
                    await clicks.async_safe_click(label, purpose="select", timeout=3000)
            if await box.is_checked():
                completed.append({"label": row["label"], "id": row["id"], "value": "checked", "key": "workday_consent"})
            else:
                unresolved.append(row["label"])
        except Exception:
            unresolved.append(row["label"])
    return completed, unresolved
from resume_tailor.apply.driver import clicks
