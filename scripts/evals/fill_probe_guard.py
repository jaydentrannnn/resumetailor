"""The network guard and request audit for `fill_probe.py --live`.

`decide` is pure: given one request it says whether it may leave the browser. A request is
aborted when it carries a made-up-applicant identity marker (in the URL or body, plain,
URL-encoded or base64), uploads a file, has a body the guard cannot read (compressed or
binary), or goes to a session-recording service. A write (a request with a body) is also
aborted when it carries one of the applicant's other answers, is a GraphQL mutation, or
goes to a save-shaped path (autosave, draft, answers, candidate...): answers such as "Yes"
or "3.7" cannot be told apart from other data, so a form save is refused by its shape.
Geocoding lookups (a typed city) may pass.

`Audit` writes one JSON line per request (method, host, path without query, size,
decision, reason) and checks every request again, whatever the decision, for the identity
and answer markers (`check`), so a run's claim "nothing carrying the applicant left" does
not rest on `decide` alone. Its summary also lists every allowed write by host and path
for review.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes, urlsplit

_READS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Session-replay and keystroke-analytics hosts: they record what is typed.
_RECORDERS = re.compile(
    r"(?:^|\.)(?:fullstory\.com|hotjar\.(?:com|io)|logrocket\.(?:com|io)|lr-ingest\.(?:com|io)|"
    r"mouseflow\.com|clarity\.ms|smartlook\.(?:com|cloud)|quantummetric\.com|contentsquare\.net|"
    r"heapanalytics\.com|glassboxdigital\.io|sessioncam\.com|inspectlet\.com|luckyorange\.(?:com|net)|"
    r"crazyegg\.com|posthog\.com|datadoghq-browser-agent\.com|browser-intake-datadoghq\.com)$",
    re.I,
)
#: Geocoding services a location box asks while the applicant types a city.
_LOOKUPS = re.compile(
    r"(?:^|\.)(?:places\.googleapis\.com|maps\.googleapis\.com|api\.mapbox\.com|"
    r"autocomplete\.search\.hereapi\.com|api\.radar\.io)$",
    re.I,
)
#: A path that saves form state.
_SAVE_PATH = re.compile(
    r"auto[-_]?save|save|draft|answers?\b|candidates?\b|submit|upload|resume|profile", re.I
)
_MUTATION = re.compile(rb"\bmutation\b")
_TEXT_TYPES = ("json", "x-www-form-urlencoded", "text/", "javascript", "xml", "graphql")
_BASE64_RUN = re.compile(rb"[A-Za-z0-9+/_-]{12,}={0,2}")


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str
    marked: bool = False


def _variants(blob: bytes) -> list[bytes]:
    """The bytes as sent, URL-decoded, and every base64 run decoded."""
    out = [blob]
    with contextlib.suppress(Exception):
        out.append(unquote_to_bytes(blob.replace(b"+", b" ")))
    for run in _BASE64_RUN.findall(blob)[:200]:
        padded = run + b"=" * (-len(run) % 4)
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                out.append(decoder(padded))
            except Exception:  # noqa: BLE001
                continue
    return out


def carries(blob: bytes, markers: tuple[bytes, ...]) -> bool:
    return any(marker in variant for variant in _variants(blob) for marker in markers)


def decide(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    markers: tuple[bytes, ...],
    answers: tuple[bytes, ...] = (),
) -> Decision:
    method = method.upper()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    lowered = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    ctype = lowered.get("content-type", "")
    if _RECORDERS.search(host):
        return Decision(False, "session recorder")
    if carries(url.encode("utf-8", "replace"), markers):
        return Decision(False, "applicant data in url", marked=True)
    if method in _READS and not body:
        return Decision(True, "read")
    if "multipart" in ctype or "pdf" in ctype or "octet-stream" in ctype or body[:5] == b"%PDF-":
        return Decision(False, "upload")
    if lowered.get("content-encoding") or (
        body and ctype and not any(t in ctype for t in _TEXT_TYPES)
    ):
        return Decision(False, "unreadable body")
    if body:
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            return Decision(False, "unreadable body")
    if carries(body, markers):
        return Decision(False, "applicant data in body", marked=True)
    if _LOOKUPS.search(host):
        return Decision(True, "lookup")
    if answers and carries(body, answers):
        return Decision(False, "applicant answers in body", marked=True)
    if _MUTATION.search(body) or _SAVE_PATH.search(parts.path):
        return Decision(False, "form write")
    return Decision(True, "write without applicant data" if method not in _READS else "read")


def check(
    url: str, body: bytes, markers: tuple[bytes, ...], answers: tuple[bytes, ...] = ()
) -> tuple[bool, bool]:
    """(identity, answered) for the audit: the markers in the URL or body, checked apart
    from `decide`."""
    blob = url.encode("utf-8", "replace") + b"\n" + body
    return carries(blob, markers), bool(answers) and carries(blob, answers)


class Audit:
    """One JSON line per request, plus counts for the report."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.counts: Counter[str] = Counter()
        self.allowed_marked = 0
        self.allowed_reads_with_answers = 0
        self.allowed_writes: Counter[str] = Counter()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")

    def record(
        self,
        method: str,
        url: str,
        size: int,
        decision: Decision,
        *,
        identity: bool = False,
        answered: bool = False,
    ) -> None:
        """``identity`` / ``answered``: the request carries an identity / answer marker, by
        the caller's own `check`, not by ``decision``. An allowed request with an identity
        marker, or an allowed write with an answer, counts as carrying applicant data; an
        allowed read with an answer (a location box's typed city) is counted apart."""
        parts = urlsplit(url)
        method = method.upper()
        self.counts[f"{'allow' if decision.allow else 'block'}: {decision.reason}"] += 1
        write = method not in _READS or size > 0
        if decision.allow:
            if identity or (answered and write and decision.reason != "lookup"):
                self.allowed_marked += 1
            elif answered:
                self.allowed_reads_with_answers += 1
            if write:
                self.allowed_writes[f"{method} {parts.hostname or ''}{parts.path[:120]}"] += 1
        self._fh.write(
            json.dumps(
                {
                    "method": method,
                    "host": parts.hostname or "",
                    "path": parts.path[:200],
                    "size": size,
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "identity": identity,
                    "answered": answered,
                }
            )
            + "\n"
        )
        self._fh.flush()

    def summary(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "allowed_with_applicant_data": self.allowed_marked,
            "allowed_reads_with_answers": self.allowed_reads_with_answers,
            "allowed_writes": dict(self.allowed_writes.most_common(60)),
        }

    def close(self) -> None:
        self._fh.close()


#: Runs before any page script: no service worker can register, so every request a page
#: makes goes through the route handler.
NO_SERVICE_WORKERS_JS = """(() => {
  try {
    if (navigator.serviceWorker) {
      Object.defineProperty(navigator.serviceWorker, 'register', {
        value: () => Promise.reject(new Error('service workers are off in the fill probe')),
      });
    }
  } catch (_) {}
})();"""


def install(
    context: Any, audit: Audit, markers: tuple[bytes, ...], answers: tuple[bytes, ...] = ()
) -> None:
    """Route every request and WebSocket of ``context`` through the guard."""

    def _route(route: Any, request: Any) -> None:
        try:
            body = request.post_data_buffer or b""
        except Exception:  # noqa: BLE001
            body = b""
        try:
            headers = request.headers
        except Exception:  # noqa: BLE001
            headers = {}
        decision = decide(request.method, request.url, headers, body, markers, answers)
        identity, answered = check(request.url, body, markers, answers)
        audit.record(
            request.method, request.url, len(body), decision, identity=identity, answered=answered
        )
        if decision.allow:
            route.continue_()
        else:
            route.abort()

    def _socket(ws: Any) -> None:
        # Never connect_to_server(): the page's socket is then a mock that reaches nobody.
        # Calling ws.close() here deadlocks the sync API (every eightfold1 run stalled
        # right after its chat widget's socket, 2026-10).
        audit.record("WEBSOCKET", ws.url, 0, Decision(False, "websocket"))

    context.add_init_script(NO_SERVICE_WORKERS_JS)
    context.route("**/*", _route)
    context.route_web_socket(re.compile(".*"), _socket)
