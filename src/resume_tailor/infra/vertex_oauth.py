"""Desktop OAuth in the system browser with a short-lived loopback listener."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from . import vertex_auth

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
]
TIMEOUT = 300
_lock = threading.RLock()
_flows: dict[str, Authorization] = {}


def client_config() -> dict | None:
    client_id = os.environ.get("RESUME_TAILOR_GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("RESUME_TAILOR_GOOGLE_CLIENT_SECRET", "")
    if not client_id:
        resource = files("resume_tailor.infra").joinpath("vertex_oauth_client.json")
        if resource.is_file():
            data = json.loads(resource.read_text("utf-8"))
            client_id = data.get("client_id", "")
            client_secret = data.get("client_secret", "")
    if not client_id or not client_secret:
        return None
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


class Authorization:
    def __init__(self, config: dict):
        from google_auth_oauthlib.flow import Flow

        self.id = secrets.token_urlsafe(24)
        self.epoch = vertex_auth.epoch()
        self.started = time.monotonic()
        self.status = "pending"
        self.detail = "Finish signing in in your browser."
        self.lock = threading.RLock()
        self.flow = Flow.from_client_config(config, scopes=SCOPES, autogenerate_code_verifier=True)
        owner = self

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Callback URLs contain authorization codes.

            def do_GET(self):
                query = parse_qs(urlsplit(self.path).query)
                supplied = query.get("state", [""])[0]
                if urlsplit(self.path).path != "/callback" or not hmac.compare_digest(
                    supplied, owner.state
                ):
                    self.send_error(400, "Invalid sign-in callback")
                    return
                owner.complete(query)
                body = b"Return to ResumeTailor to finish connecting Google Cloud."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), Callback)
        self.server.timeout = 0.25
        self.flow.redirect_uri = f"http://127.0.0.1:{self.server.server_port}/callback"
        self.url, self.state = self.flow.authorization_url(
            access_type="offline",
            prompt="consent select_account",
        )
        self.thread = threading.Thread(target=self.listen, name="vertex-oauth", daemon=True)

    def listen(self) -> None:
        try:
            while self.status == "pending" and time.monotonic() - self.started < TIMEOUT:
                self.server.handle_request()
            with self.lock:
                if self.status == "pending":
                    self.status, self.detail = "expired", "Sign-in timed out. Connect again."
        finally:
            self.server.server_close()

    def complete(self, query: dict) -> None:
        with self.lock:
            if self.status != "pending":
                return
            if time.monotonic() - self.started >= TIMEOUT:
                self.status, self.detail = "expired", "Sign-in timed out. Connect again."
                return
            if query.get("error") or not query.get("code"):
                self.status, self.detail = "cancelled", "Google sign-in was cancelled or denied."
                return
        try:
            # Cancellation remains responsive while Google is answering.
            info, email = self.exchange(query["code"][0])
            with self.lock:
                if self.status != "pending":
                    return
                if time.monotonic() - self.started >= TIMEOUT:
                    self.status, self.detail = "expired", "Sign-in timed out. Connect again."
                    return
                vertex_auth.save(info, email, self.epoch)
                self.status, self.detail = "connected", "Google Cloud connected."
        except Exception as exc:  # noqa: BLE001 - never expose OAuth provider errors
            with self.lock:
                if self.status == "pending":
                    self.status = "failed"
                    self.detail = (
                        str(exc)
                        if isinstance(exc, vertex_auth.ConnectionError)
                        else "Google sign-in could not finish. Connect again."
                    )
        finally:
            self.flow.oauth2session.token = {}

    def exchange(self, code: str) -> tuple[dict, str]:
        import requests

        self.flow.fetch_token(code=code, timeout=20)
        creds = self.flow.credentials
        granted = set(creds.granted_scopes or creds.scopes or [])
        if not set(SCOPES).issubset(granted):
            raise vertex_auth.ConnectionError("Grant Google Cloud access to connect Vertex AI.")
        response = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=15,
        )
        response.raise_for_status()
        email = response.json().get("email", "")
        if not email:
            raise vertex_auth.ConnectionError(
                "Google did not return your account email. Reconnect."
            )
        info = json.loads(creds.to_json())
        info.pop("token", None)
        info.pop("expiry", None)
        info["type"] = "authorized_user"
        return info, email

    def cancel(self) -> None:
        with self.lock:
            if self.status == "pending":
                self.status, self.detail = "cancelled", "Sign-in cancelled."
            self.flow.oauth2session.token = {}


def start() -> dict:
    config = client_config()
    if not config:
        raise vertex_auth.ConnectionError(
            "Google connection unavailable: configure ResumeTailor's Desktop OAuth client."
        )
    with _lock:
        cancel_all()
        _flows.clear()
        auth = Authorization(config)
        _flows[auth.id] = auth
        auth.thread.start()
        return {"flow_id": auth.id, "authorization_url": auth.url}


def status(flow_id: str) -> dict:
    with _lock:
        auth = _flows.get(flow_id)
        if auth is None:
            raise KeyError(flow_id)
        return {"status": auth.status, "detail": auth.detail}


def cancel(flow_id: str) -> None:
    with _lock:
        if flow_id not in _flows:
            raise KeyError(flow_id)
        _flows[flow_id].cancel()


def cancel_all() -> None:
    with _lock:
        for auth in _flows.values():
            auth.cancel()
