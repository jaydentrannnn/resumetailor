"""Which application platform a page belongs to, from its URL and a few page signals.

`fetch_jd.detect_ats` reads a posting URL's host. A company careers domain often hosts or
hands over to a known platform (Oracle under ``careers.<company>.com``, Eightfold under a
company's own domain, a Jibe page sending the applicant to iCIMS), so the fill checks the
page it actually lands on (`identify`). A platform's own host or path is enough alone;
page signals (custom element names, iframe and script hosts) need two that agree, because
one component name or script can appear on an unrelated site.

Names beyond `fetch_jd.AtsName` ("eightfold", "avature", "jibe") are platform names for
diagnostics; `stored_ats` keeps the stored `Application.ats` to names older app versions
can read.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

#: Custom element names, iframe ids and hosts, and script hosts, through open shadow roots.
SIGNALS_JS = r"""() => {
  const elements = new Set();
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      const tag = el.tagName.toLowerCase();
      if (tag.includes('-')) elements.add(tag);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  const host = (src) => {
    try { return new URL(src, location.href).hostname; } catch (_) { return ''; }
  };
  const hosts = (srcs) => [...new Set(srcs.map(host).filter(Boolean))];
  const frames = [...document.querySelectorAll('iframe')];
  return {
    elements: [...elements].slice(0, 200),
    iframe_ids: frames.map((f) => f.id || '').filter(Boolean).slice(0, 20),
    iframe_hosts: hosts(frames.map((f) => f.src)).slice(0, 20),
    script_hosts: hosts([...document.scripts].map((s) => s.src)).slice(0, 40),
  };
}"""

_ORACLE_PATH = re.compile(r"/hcmui/candidateexperience/", re.I)
_EIGHTFOLD_PATH = re.compile(r"/careers/job/\d{9,}", re.I)
_AVATURE_PATH = re.compile(
    r"/careers/(?:JobDetail|ApplicationMethods|Login|Register|SubmitResume|FolderDetail|SearchJobs)\b",
    re.I,
)
_HTML_ELEMENT = re.compile(r"<([a-z][a-z0-9]*-[a-z0-9-]+)[\s>/]", re.I)
_HTML_IFRAME = re.compile(r"<iframe\b[^>]*>", re.I)
_HTML_SCRIPT = re.compile(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", re.I)
_ATTR = re.compile(r"\b(id|src)=[\"']([^\"']*)", re.I)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _under(host: str, *domains: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def from_signals(url: str, signals: dict[str, Any] | None) -> str | None:
    """The platform the URL or page signals point to, or None when nothing is clear."""
    host, path = _host(url), urlsplit(url).path
    if _under(host, "icims.com"):
        return "icims"
    if _under(host, "smartrecruiters.com"):
        return "smartrecruiters"
    if _under(host, "eightfold.ai"):
        return "eightfold"
    if _under(host, "avature.net"):
        return "avature"
    if _under(host, "jibeapply.com"):
        return "jibe"
    if _ORACLE_PATH.search(path):
        return "oracle"
    signals = signals or {}
    elements = {str(e).lower() for e in signals.get("elements") or []}
    iframe_ids = {str(i).lower() for i in signals.get("iframe_ids") or []}
    iframe_hosts = [str(h).lower() for h in signals.get("iframe_hosts") or []]
    script_hosts = [str(h).lower() for h in signals.get("script_hosts") or []]
    if "apply-flow-header" in elements and any(e.startswith("oj-") for e in elements):
        return "oracle"
    if "oc-oneclick-form-root" in elements and any(e.startswith("spl-") for e in elements):
        return "smartrecruiters"
    if "icims_content_iframe" in iframe_ids and any(_under(h, "icims.com") for h in iframe_hosts):
        return "icims"
    eightfold_assets = any(_under(h, "eightfold.ai", "vscdn.net") for h in script_hosts)
    if _EIGHTFOLD_PATH.search(path) and ("apply-widget" in elements or eightfold_assets):
        return "eightfold"
    if "portal-data" in elements and _AVATURE_PATH.search(path):
        return "avature"
    return None


def signals_from_html(html: str) -> dict[str, list[str]]:
    """The same signals from fetched HTML (no shadow roots: those are built by script)."""
    iframe_ids, iframe_hosts = [], []
    for tag in _HTML_IFRAME.findall(html or "")[:20]:
        attrs = {k.lower(): v for k, v in _ATTR.findall(tag)}
        if attrs.get("id"):
            iframe_ids.append(attrs["id"])
        if attrs.get("src"):
            iframe_hosts.append(_host(attrs["src"]))
    return {
        "elements": sorted({m.lower() for m in _HTML_ELEMENT.findall(html or "")})[:200],
        "iframe_ids": iframe_ids,
        "iframe_hosts": [h for h in iframe_hosts if h],
        "script_hosts": [h for h in (_host(s) for s in _HTML_SCRIPT.findall(html or "")[:40]) if h],
    }


def identify(url: str, signals: dict[str, Any] | None = None) -> str:
    """The URL's platform when its host names one, else what the page signals show, else
    "other"/"unknown" from the URL."""
    from resume_tailor.apply.discovery import fetch_jd  # noqa: PLC0415 - fetch_jd imports us

    known = fetch_jd.detect_ats(url)
    if known not in {"other", "unknown"}:
        return known
    return from_signals(url, signals) or known


def page_platform(page: Any) -> str:
    """`identify` for a live page; "" when the page cannot be read (navigating)."""
    try:
        return identify(str(page.url), page.evaluate(SIGNALS_JS))
    except Exception:  # noqa: BLE001
        return ""


def stored_ats(platform: str) -> str | None:
    """The `Application.ats` value for ``platform``, or None when it has none: a new
    ``AtsKind`` name would make older app versions fail to read the row."""
    from typing import get_args  # noqa: PLC0415

    from resume_tailor.apply.funnel.store_models import AtsKind  # noqa: PLC0415

    return platform if platform in get_args(AtsKind) else None
