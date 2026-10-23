"""GET public web pages politely and safely: the one door for research and evidence fetches.

- GET only, with an honest user agent (`USER_AGENT`), a 20 s timeout, at most 5
  redirects (followed by hand, each hop checked again) and a 5 MB cap on the body.
- Only http(s) to public addresses. A host that resolves to a private, loopback,
  link-local (cloud metadata), multicast or reserved address is refused. The check runs
  before each request and again when the socket connects (`_GuardedBackend`), so a DNS
  answer that changes between the two cannot slip through.
- robots.txt is honoured (`robots.py`). A missing one (404/410) allows everything; any
  other failure to read it blocks the host. It is read once per host per `Fetcher`.
- No proxy from the environment (``trust_env=False``): the address check has to see the
  real destination.

Returns the raw body as text; `research/pages.py` turns a page into readable, guarded text.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Any

import httpcore
import httpx

from resume_tailor import __version__

from . import robots

USER_AGENT = f"ResumeTailor/{__version__} (personal job search; reads robots.txt)"
TIMEOUT = 20.0
MAX_REDIRECTS = 5
MAX_BYTES = 5 * 1024 * 1024
#: RFC 9309 asks crawlers to read at least 500 KiB of a robots.txt; the rest is ignored.
ROBOTS_MAX_BYTES = 512 * 1024

PAGE_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown")
JSON_TYPES = ("application/json",)


class FetchError(Exception):
    """A page that was not fetched; the message says why in plain words."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        #: The HTTP status the server answered with, when it answered at all.
        self.status = status


@dataclass(frozen=True)
class Fetched:
    #: Where the page was found, after redirects.
    url: str
    content_type: str
    text: str


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _public_addresses(host: str, port: int) -> list[str]:
    """The addresses ``host`` resolves to, all public, or a `FetchError`."""
    try:
        addresses = _resolve(host, port)
    except (OSError, UnicodeError) as exc:
        raise FetchError(f"{host} could not be found.") from exc
    if not addresses or not all(_public(a) for a in addresses):
        raise FetchError(f"{host} is not a public web address, so it is not read.")
    return addresses


def _checked(url: str | httpx.URL) -> httpx.URL:
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError) as exc:
        raise FetchError("That is not a web address.") from exc
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise FetchError("Only http and https web addresses can be read.")
    if parsed.userinfo:
        raise FetchError("Web addresses with a user name or password are not read.")
    _public_addresses(parsed.host, parsed.port or (443 if parsed.scheme == "https" else 80))
    return parsed


class _GuardedBackend(httpcore.SyncBackend):
    """Connects only to public addresses, resolved and checked at connect time."""

    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None,
                    socket_options: Any = None) -> httpcore.NetworkStream:
        try:
            address = _public_addresses(host, port)[0]
        except FetchError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        # TLS still verifies the certificate against ``host``: httpcore passes the
        # origin's name as the server hostname, not this address.
        return super().connect_tcp(address, port, timeout, local_address, socket_options)


def _transport() -> httpx.BaseTransport:
    transport = httpx.HTTPTransport(trust_env=False)
    # httpx has no public hook for the network backend; its connection pool takes one.
    transport._pool._network_backend = _GuardedBackend()  # noqa: SLF001
    return transport


def _media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";")[0].strip().lower()


class Fetcher:
    """One run's fetches. robots.txt is read once per host and remembered until closed."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            transport=transport or _transport(), timeout=TIMEOUT, follow_redirects=False,
            headers={"User-Agent": USER_AGENT}, trust_env=False,
        )
        self._robots: dict[str, robots.Rules] = {}

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, url: str, *, types: tuple[str, ...] = PAGE_TYPES,
            headers: dict[str, str] | None = None) -> Fetched:
        """GET ``url`` (a page by default), following redirects by hand. ``headers`` (a
        token, say) go only to ``url``'s own host, never to a host it redirects to."""
        current: str | httpx.URL = url
        start = _checked(url)
        home = (start.scheme, start.host, start.port)
        for _ in range(MAX_REDIRECTS + 1):
            parsed = _checked(current)
            if not self._rules(parsed).allows(parsed.raw_path.decode("ascii") or "/"):
                raise FetchError(
                    f"{parsed.host} asks automated tools not to read this page (robots.txt)."
                )
            extra = headers if (parsed.scheme, parsed.host, parsed.port) == home else None
            response, body = self._send(parsed, ", ".join(types), MAX_BYTES, headers=extra)
            if response.is_redirect:
                current = parsed.join(response.headers["location"])
                continue
            if response.status_code != 200:
                raise FetchError(f"{parsed.host} answered {response.status_code}.",
                                 status=response.status_code)
            media = _media_type(response)
            if media not in types:
                raise FetchError(f"{parsed.host} sent {media or 'an unknown type'}, not a page.")
            text = body.decode(response.charset_encoding or "utf-8", errors="replace")
            return Fetched(str(parsed), media, text)
        raise FetchError("The page redirected too many times.")

    def get_json(self, url: str, *, headers: dict[str, str] | None = None) -> Any:
        """GET ``url`` and parse its JSON body."""
        fetched = self.get(url, types=JSON_TYPES, headers=headers)
        try:
            return json.loads(fetched.text)
        except json.JSONDecodeError as exc:
            raise FetchError(f"{httpx.URL(fetched.url).host} sent JSON that won't parse.") from exc

    def _send(self, url: httpx.URL, accept: str, cap: int, *, truncate: bool = False,
              headers: dict[str, str] | None = None) -> tuple[httpx.Response, bytes]:
        try:
            with self._client.stream("GET", url,
                                     headers={**(headers or {}), "Accept": accept}) as response:
                if response.is_redirect:
                    return response, b""
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > cap:
                        if truncate:
                            chunks.append(chunk[: len(chunk) - (size - cap)])
                            break
                        raise FetchError(f"{url.host} sent more than {cap // 1_048_576} MB.")
                    chunks.append(chunk)
                return response, b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise FetchError(f"{url.host} did not answer within {TIMEOUT:.0f} seconds.") from exc
        except httpx.ConnectError as exc:
            cause = str(exc)
            raise FetchError(cause if "public web address" in cause
                             else f"{url.host} could not be reached.") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"{url.host} could not be reached.") from exc

    def _rules(self, url: httpx.URL) -> robots.Rules:
        origin = f"{url.scheme}://{url.netloc.decode('ascii')}"
        if origin not in self._robots:
            self._robots[origin] = self._read_robots(
                url.copy_with(path="/robots.txt", query=None, fragment=None)
            )
        return self._robots[origin]

    def _read_robots(self, url: httpx.URL) -> robots.Rules:
        current = url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                response, body = self._send(_checked(current), "text/plain", ROBOTS_MAX_BYTES,
                                            truncate=True)
                if response.is_redirect:
                    current = current.join(response.headers["location"])
                    continue
                if response.status_code in (404, 410):
                    return robots.ALLOW_ALL
                if response.status_code != 200:
                    return robots.DISALLOW_ALL
                return robots.parse(body.decode("utf-8", errors="replace"))
        except FetchError:
            pass
        return robots.DISALLOW_ALL
