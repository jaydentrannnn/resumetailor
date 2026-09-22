"""Hermetic tests for Chrome CDP URL rewriting under Docker Host rules."""

from __future__ import annotations

from resume_tailor.apply import browser


def test_effective_cdp_url_leaves_localhost(monkeypatch):
    """Localhost URLs are already Chrome-legal and must not be rewritten."""
    assert (
        browser.effective_cdp_url("http://localhost:9222") == "http://localhost:9222"
    )
    assert (
        browser.effective_cdp_url("http://127.0.0.1:9222") == "http://127.0.0.1:9222"
    )


def test_effective_cdp_url_resolves_docker_gateway(monkeypatch):
    """``host.docker.internal`` must become an IP so Chrome accepts the Host header."""

    def _fake_gethostbyname(name: str) -> str:
        """Stub DNS for the Docker Desktop gateway hostname."""
        assert name == "host.docker.internal"
        return "192.168.65.254"

    monkeypatch.setattr(browser.socket, "gethostbyname", _fake_gethostbyname)
    assert (
        browser.effective_cdp_url("http://host.docker.internal:9222")
        == "http://192.168.65.254:9222"
    )


def test_browser_status_uses_effective_url(monkeypatch):
    """Status probe must hit the IP form, not the unresolved gateway hostname."""
    seen: list[str] = []

    class _Resp:
        """Minimal httpx-like response for the version probe."""

        def raise_for_status(self) -> None:
            """No-op success."""
            return None

        def json(self) -> dict:
            """Return a fake Chrome version payload."""
            return {"Browser": "Chrome/1", "User-Agent": "ua"}

    def _fake_get(url: str, **kwargs):
        """Record the probed URL and return success."""
        seen.append(url)
        return _Resp()

    monkeypatch.setattr(
        browser.config, "CHROME_CDP_URL", "http://host.docker.internal:9222"
    )
    monkeypatch.setattr(
        browser, "effective_cdp_url", lambda url=None: "http://192.168.65.254:9222"
    )
    monkeypatch.setattr(browser.httpx, "get", _fake_get)
    status = browser.browser_status()
    assert status.reachable is True
    assert seen == ["http://192.168.65.254:9222/json/version"]
    assert status.cdp_url == "http://host.docker.internal:9222"
