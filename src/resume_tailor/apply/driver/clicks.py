"""Every click the Apply funnel makes on a job site goes through this module.

Why: a Workday Review page's "Next" was once a Submit, and an application went out
that nobody had reviewed. The apply modules had ~50 raw ``.click()`` calls and only
three checked what they were about to press. Now:

- `safe_click` / `async_safe_click` take a ``purpose``. Buttons pressed to move
  through a form (``advance``, ``enter``, ``dismiss``) are refused when their text,
  ``aria-label`` or ``value`` reads as submitting the application, or when that text
  cannot be read at all (fail closed). ``select`` (options, labels, checkboxes)
  refuses a real submit control. ``auth`` (Sign In, Create Account, the email-route
  chooser) is not text-checked, because Workday labels its sign-in overlay "Submit".
  Only the auth flows use it.
- `submit_click` is the one function that may press a final submit, and only with an
  ``auto_submit`` decision from `fill.decide_submit_action`.
- `mouse_click` / `async_mouse_click` wrap coordinate clicks (Workday's click-filter
  overlays) with the same check on whatever element sits at that point.

`tests/apply/driver/test_click_guard.py` fails if a ``.click(`` appears anywhere else under
``apply/``.
"""

from __future__ import annotations

import re
from typing import Any, Literal

Purpose = Literal["advance", "enter", "dismiss", "select", "auth", "upload"]

#: Text that means "this sends the application". "Apply" alone is not here: it opens
#: an application (posting pages, Workday's "Apply Manually").
SUBMIT_TEXT = re.compile(
    r"\b(submit|send application|send my application|finish|complete application|"
    r"complete and submit|review and submit|apply and submit)\b",
    re.IGNORECASE,
)

#: Purposes whose target must not read as a submit.
_TEXT_CHECKED: frozenset[str] = frozenset({"advance", "enter", "dismiss", "upload"})

_LABEL_JS = """el => [el.innerText || '', el.getAttribute('aria-label') || '',
  el.getAttribute('value') || '', el.getAttribute('title') || ''].join(' ')"""

#: Is this a submit input, or a button-like control (so not an option or a label)?
_CONTROL_KIND_JS = """el => {
  const tag = el.tagName;
  const type = (el.getAttribute('type') || '').toLowerCase();
  return {
    submitInput: tag === 'INPUT' && type === 'submit',
    buttonish: tag === 'BUTTON' || (tag === 'INPUT' && ['button', 'image'].includes(type))
      || el.getAttribute('role') === 'button',
    label: [el.innerText || '', el.getAttribute('aria-label') || '',
      el.getAttribute('value') || ''].join(' '),
  };
}"""

_POINT_LABEL_JS = """([x, y]) => {
  const el = document.elementFromPoint(x, y);
  const target = el && (el.closest('button, a, [role="button"], input') || el);
  return target ? [target.innerText || '', target.getAttribute('aria-label') || '',
    target.getAttribute('value') || ''].join(' ') : '';
}"""


class SubmitRefused(RuntimeError):
    """A click was refused because it would (or might) submit the application."""


def reads_as_submit(text: str) -> bool:
    return bool(SUBMIT_TEXT.search(text or ""))


def _label(loc: Any) -> str:
    if not hasattr(loc, "evaluate"):  # minimal locator stand-ins (tests)
        return f"{loc.inner_text(timeout=1000) or ''} {loc.get_attribute('aria-label') or ''}"
    return str(loc.evaluate(_LABEL_JS, timeout=1000))


async def _async_label(loc: Any) -> str:
    if not hasattr(loc, "evaluate"):
        text = await loc.inner_text(timeout=1000)
        return f"{text or ''} {await loc.get_attribute('aria-label') or ''}"
    return str(await loc.evaluate(_LABEL_JS, timeout=1000))


def is_submit_like(loc: Any) -> bool:
    """True when ``loc`` reads as a submit, or its text cannot be read (fail closed)."""
    try:
        return reads_as_submit(_label(loc))
    except Exception:  # noqa: BLE001 - unreadable: never treat as a safe advance
        return True


async def async_is_submit_like(loc: Any) -> bool:
    try:
        return reads_as_submit(await _async_label(loc))
    except Exception:  # noqa: BLE001
        return True


def _submit_control(kind: Any) -> bool:
    if not isinstance(kind, dict):
        return False
    return bool(kind.get("submitInput")) or (
        bool(kind.get("buttonish")) and reads_as_submit(str(kind.get("label") or ""))
    )


def _is_submit_control(loc: Any) -> bool:
    """A submit input, or a button whose text reads as submit. Options never are."""
    try:
        return _submit_control(loc.evaluate(_CONTROL_KIND_JS, timeout=1000))
    except Exception:  # noqa: BLE001 - the click itself will report a missing element
        return False


async def _async_is_submit_control(loc: Any) -> bool:
    try:
        return _submit_control(await loc.evaluate(_CONTROL_KIND_JS, timeout=1000))
    except Exception:  # noqa: BLE001
        return False


def _refuse(purpose: str) -> SubmitRefused:
    return SubmitRefused(
        f"refused a {purpose} click on a control that reads as submitting the application"
    )


def safe_click(loc: Any, *, purpose: Purpose, **kwargs: Any) -> None:
    """Click ``loc`` for ``purpose``; raise `SubmitRefused` rather than submit."""
    if purpose in _TEXT_CHECKED and is_submit_like(loc):
        raise _refuse(purpose)
    if purpose == "select" and _is_submit_control(loc):
        raise _refuse(purpose)
    loc.click(**kwargs)


async def async_safe_click(loc: Any, *, purpose: Purpose, **kwargs: Any) -> None:
    if purpose in _TEXT_CHECKED and await async_is_submit_like(loc):
        raise _refuse(purpose)
    if purpose == "select" and await _async_is_submit_control(loc):
        raise _refuse(purpose)
    await loc.click(**kwargs)


def submit_click(loc: Any, *, decision: str, **kwargs: Any) -> None:
    """Press the final submit. Only an ``auto_submit`` decision may reach a click."""
    if decision != "auto_submit":
        raise SubmitRefused(f"submit_click needs an auto_submit decision, got {decision!r}")
    loc.click(**kwargs)


def mouse_click(page: Any, x: float, y: float, *, purpose: Purpose) -> None:
    """Click at a point (under an overlay), checking the element found there."""
    if purpose in _TEXT_CHECKED:
        try:
            label = page.evaluate(_POINT_LABEL_JS, [x, y])
        except Exception:  # noqa: BLE001 - unreadable: fail closed
            raise _refuse(purpose) from None
        if reads_as_submit(str(label)):
            raise _refuse(purpose)
    page.mouse.click(x, y)


async def async_mouse_click(page: Any, x: float, y: float, *, purpose: Purpose) -> None:
    if purpose in _TEXT_CHECKED:
        try:
            label = await page.evaluate(_POINT_LABEL_JS, [x, y])
        except Exception:  # noqa: BLE001
            raise _refuse(purpose) from None
        if reads_as_submit(str(label)):
            raise _refuse(purpose)
    await page.mouse.click(x, y)
