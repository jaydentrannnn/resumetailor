"""Capture an application page for building test fixtures, and sanitize the capture.

`capture(page_or_frame, path)` saves the document with its open shadow roots (as
declarative ``<template shadowrootmode>``) and marks elements the browser does not render
(``data-rt-hidden``), because a fixture is replayed without the site's stylesheets.
Raw captures belong in a gitignored folder (``output/captures``).

`sanitize(html, renames, known)` is what may go near ``tests/fixtures/forms``: it clears
values, checked/selected state and hidden-input values, custom widgets' shown selections
(a dropdown's chosen text, multi-select chips, ``aria-selected``/``aria-valuetext``),
embedded state (``data-*`` JSON or long values, ``data-value``), removes scripts (JSON
blobs included), iframes' and links' URL queries, attachment names, emails and phone
numbers, and replaces the company names in ``renames`` and every ``known`` value (the
probe's made-up applicant by default) wherever they appear.

`leaks` is a pattern check, not a proof: a page can show an applicant's answer as plain
text (a review page) that no pattern recognises. Every sanitized copy is read before a
fixture is built from it; fixtures are minimal anonymized reconstructions, as the existing
ones are.

    python scripts/evals/capture_form.py sanitize RAW.html OUT.html --rename "Acme Corp=Example Co"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment

CAPTURE_JS = r"""() => {
  const roots = [];
  const marked = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      const rendered = el.offsetWidth || el.offsetHeight || el.getClientRects().length;
      const style = getComputedStyle(el);
      if (!rendered || style.visibility === 'hidden' || style.opacity === '0') {
        el.setAttribute('data-rt-hidden', '1');
        marked.push(el);
      }
      if (el.shadowRoot) { roots.push(el.shadowRoot); walk(el.shadowRoot); }
    }
  };
  walk(document);
  const html = document.documentElement.getHTML(
    { serializableShadowRoots: true, shadowRoots: roots });
  marked.forEach((el) => el.removeAttribute('data-rt-hidden'));
  return { html, url: location.href, title: document.title, shadow_roots: roots.length };
}"""

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_FILE_NAME = re.compile(r"[\w() .-]+\.(?:pdf|docx?|rtf|txt|odt|pages)\b", re.I)
_URL_ATTRS = ("href", "src", "action", "data-src", "formaction", "poster")
#: A custom widget's shown selection: React Select's value, chips, a combobox's own text.
_SELECTION_CLASS = re.compile(
    r"single-?value|multi-?value|selected-?value|select__value|value-?container|chip|"
    r"selection|token|pill|tag-?label",
    re.I,
)
#: State attributes that hold an answer, or say which option is the answer.
_STATE_ATTRS = ("aria-valuetext", "aria-valuenow", "data-value", "data-selected",
                "data-initial-value", "data-default-value")
_TRUE_STATES = ("aria-selected", "aria-checked", "aria-pressed")
#: A ``data-*`` value this long, or shaped like JSON, is embedded state, not a hook.
_DATA_LIMIT = 80


def _known_values() -> list[str]:
    """The made-up applicant's values (`fill_probe_data`), longest first."""
    try:
        import fill_probe_data as synth  # noqa: PLC0415 - run as a script from scripts/evals
    except ImportError:
        try:
            from evals import fill_probe_data as synth  # noqa: PLC0415
        except ImportError:
            return []
    values = {synth.FIRST, synth.LAST, synth.EMAIL, synth.PHONE}
    values |= {v.decode() for v in (*synth.MARKERS, *synth.ANSWER_MARKERS)}
    return sorted((v for v in values if len(v) >= 4), key=len, reverse=True)


def capture(target: Any, path: Path) -> dict[str, Any]:
    """Save ``target``'s (a Playwright page or frame) document to ``path``."""
    snap = target.evaluate(CAPTURE_JS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<!doctype html>\n{snap['html']}", encoding="utf-8")
    return {k: snap[k] for k in ("url", "title", "shadow_roots")}


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _scrub(text: str, renames: dict[str, str], known: list[str] | None = None) -> str:
    for old, new in renames.items():
        text = re.sub(re.escape(old), new, text, flags=re.I)
    for value in known or []:
        text = re.sub(re.escape(value), "Example", text, flags=re.I)
    text = _EMAIL.sub("person@example.com", text)
    text = _PHONE.sub("555-0100", text)
    return _FILE_NAME.sub("attachment.pdf", text)


def _clear_selection(el: Any) -> None:
    """Clear a custom widget's shown selection and the attributes naming its answer."""
    classes = " ".join(el.get("class") or []) if isinstance(el.get("class"), list) else ""
    role = (el.get("role") or "").lower()
    shown = _SELECTION_CLASS.search(classes) or role == "combobox"
    if shown and el.name != "input" and not el.find(["input", "select", "option", "li", "button"]):
        el.clear()
    for attr in _STATE_ATTRS:
        el.attrs.pop(attr, None)
    for attr in _TRUE_STATES:
        if el.get(attr) == "true":
            el[attr] = "false"
    for attr, value in list(el.attrs.items()):
        if attr.startswith("data-") and isinstance(value, str) and (
            len(value) > _DATA_LIMIT or value.lstrip()[:1] in {"{", "["}
        ):
            del el.attrs[attr]


def sanitize(
    html: str, renames: dict[str, str] | None = None, known: list[str] | None = None
) -> str:
    renames = renames or {}
    known = _known_values() if known is None else known
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(["script", "noscript", "link", "meta", "object", "embed"]):
        if node.name == "meta" and node.get("charset"):
            continue
        node.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for el in soup.find_all(True):
        if el.name == "input":
            if (el.get("type") or "").lower() not in {"radio", "checkbox", "submit", "button"}:
                el.attrs.pop("value", None)
            el.attrs.pop("checked", None)
        if el.name == "option":
            el.attrs.pop("selected", None)
        if el.name == "textarea":
            el.clear()
        if el.has_attr("contenteditable"):
            el.clear()
        _clear_selection(el)
        for attr in _URL_ATTRS:
            if el.has_attr(attr) and isinstance(el[attr], str):
                el[attr] = _strip_query(el[attr])
        for attr, value in list(el.attrs.items()):
            if attr.startswith("on"):
                del el.attrs[attr]
            elif isinstance(value, str) and attr not in _URL_ATTRS:
                el[attr] = _scrub(value, renames, known)
    for text in soup.find_all(string=True):
        if not isinstance(text, Comment) and text.strip():
            text.replace_with(_scrub(str(text), renames, known))
    return str(soup)


def leaks(html: str, known: list[str] | None = None) -> list[str]:
    """What a sanitized fixture must not contain (the fixture test checks this). An empty
    list says no pattern or known value is left, not that no applicant value is."""
    found = []
    known = _known_values() if known is None else known
    if any(value.casefold() in html.casefold() for value in known):
        found.append("known value")
    if any(m != "person@example.com" for m in _EMAIL.findall(html)):
        found.append("email")
    if any(m != "555-0100" for m in _PHONE.findall(html)):
        found.append("phone")
    if re.search(r"""(?:href|src|action)=["'][^"']*\?""", html):
        found.append("url query")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    clean = sub.add_parser("sanitize")
    clean.add_argument("raw", type=Path)
    clean.add_argument("out", type=Path)
    clean.add_argument("--rename", action="append", default=[], help="Old=New, repeatable")
    args = parser.parse_args()
    renames = dict(item.split("=", 1) for item in args.rename)
    cleaned = sanitize(args.raw.read_text(encoding="utf-8"), renames)
    args.out.write_text(cleaned, encoding="utf-8")
    left = leaks(cleaned)
    nothing = "no email, phone, URL query or known value"
    print("pattern check:", ", ".join(left) if left else nothing)
    print("Read the copy before building a fixture: plain-text answers have no pattern.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
