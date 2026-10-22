"""PUT/GET /api/appearance and desktop autostart routes."""

from __future__ import annotations


def test_appearance_api_round_trip(client, tmp_path, monkeypatch):
    """PUT /api/appearance merges; GET returns the saved values."""
    test_client, _queue = client
    monkeypatch.setenv("RESUME_TAILOR_THEME_PATH", str(tmp_path / "theme.json"))
    response = test_client.put("/api/appearance", json={"accent": "#2563eb", "scale": 1.1})
    assert response.status_code == 200
    body = response.json()
    assert body["accent"] == "#2563eb"
    assert body["scale"] == 1.1
    cleared = test_client.put("/api/appearance", json={"accent": None})
    assert cleared.json()["accent"] is None
    assert cleared.json()["scale"] == 1.1
    got = test_client.get("/api/appearance")
    assert got.json()["scale"] == 1.1


def test_autostart_404_outside_desktop(client):
    """Autostart routes are desktop-only."""
    test_client, _queue = client
    assert test_client.get("/api/desktop/autostart").status_code == 404
    assert test_client.put("/api/desktop/autostart", json={"enabled": True}).status_code == 404
