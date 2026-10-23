"""The email account the app checks itself (`apply/funnel/mail_sync.py`, `mail_imap.py`).

The password is write-only: it goes to the OS keychain (`infra/secret_store`) and no
response carries it, only whether one is saved. A check runs on a background thread;
the Tracker's polling shows its result.
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor.apply.funnel import mail_imap, mail_inbox, mail_sync
from resume_tailor.infra import secret_store

router = APIRouter()
_log = logging.getLogger(__name__)


class AccountView(BaseModel):
    host: str = ""
    port: int = 993
    username: str = ""
    password_set: bool = False
    every_hours: int = 3
    auto_close: bool = False
    last_checked: str = ""
    last_error: str = ""
    last_result: mail_inbox.IngestResult | None = None
    running: bool = False
    #: Pending rejections `auto_close` would record now.
    confident_pending: int = 0


class AccountWrite(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=320)
    #: Empty keeps the saved password.
    password: str = Field(default="", max_length=1024)
    every_hours: int = 3
    auto_close: bool = False


class TestRequest(BaseModel):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(default="", max_length=320)
    password: str = Field(default="", max_length=1024)


class TestResult(BaseModel):
    folders: int


def _password_set() -> bool:
    try:
        return bool(mail_sync.password())
    except secret_store.SecretStoreError:
        return False


def view() -> AccountView:
    settings = mail_sync.load()
    account = settings.imap
    return AccountView(
        host=account.host if account else "", port=account.port if account else 993,
        username=account.username if account else "", password_set=_password_set(),
        every_hours=settings.every_hours, auto_close=settings.auto_close,
        last_checked=settings.last_checked, last_error=settings.last_error,
        last_result=settings.last_result, running=mail_sync.running(),
        confident_pending=sum(1 for p in mail_inbox.pending() if p.confident),
    )


def _account(host: str, port: int, username: str) -> mail_imap.MailAccount:
    try:
        return mail_imap.MailAccount(host=host.strip(), port=port, username=username.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Enter the server as a name like mail.example.com."
        ) from exc


@router.get("/api/mail/account", response_model=AccountView)
def get_account() -> AccountView:
    return view()


@router.put("/api/mail/account", response_model=AccountView)
def put_account(body: AccountWrite) -> AccountView:
    if body.every_hours not in mail_sync.CHECK_EVERY:
        raise HTTPException(status_code=422, detail="Pick how often to check from the list.")
    account = _account(body.host, body.port, body.username)
    try:
        if body.password:
            mail_sync.set_password(body.password)
    except secret_store.SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not _password_set():
        raise HTTPException(status_code=422, detail="Enter the password for this account.")

    switched_on: list[bool] = []

    def mutate(settings: mail_sync.Settings) -> None:
        if settings.imap != account:  # A new mailbox starts its reading over.
            settings.last_checked = settings.last_since = settings.last_error = ""
        switched_on.append(body.auto_close and not settings.auto_close)
        settings.imap, settings.every_hours = account, body.every_hours
        settings.auto_close = body.auto_close
    mail_sync.update(mutate)
    if switched_on[0]:  # "N would close now" means now, not at the next check.
        mail_inbox.auto_close()
    return view()


@router.delete("/api/mail/account", response_model=AccountView)
def delete_account() -> AccountView:
    """Forget the account and its password. Mail already read stays as proposals."""
    try:
        mail_sync.forget()
    except secret_store.SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return view()


@router.post("/api/mail/account/test", response_model=TestResult)
def test_account(body: TestRequest) -> TestResult:
    """Log in once and count the folders, with the form's values or the saved ones."""
    saved = mail_sync.load().imap
    host = body.host or (saved.host if saved else "")
    username = body.username or (saved.username if saved else "")
    if not host or not username:
        raise HTTPException(status_code=422, detail="Enter the server and username first.")
    password = body.password or mail_sync.password()
    if not password:
        raise HTTPException(status_code=422, detail="Enter the password first.")
    try:
        folders = mail_imap.test(_account(host, body.port, username), password)
    except mail_imap.MailAuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except mail_imap.MailError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TestResult(folders=folders)


def _check() -> None:
    try:
        mail_sync.run()
    except mail_sync.AlreadyRunning:
        pass
    except Exception:  # noqa: BLE001 - a background check must never take the server down
        _log.exception("mail check failed")


@router.post("/api/mail/account/check", response_model=AccountView)
def check_now() -> AccountView:
    """Start a check now; the Tracker and this page poll for its result."""
    if mail_sync.load().imap is None:
        raise HTTPException(status_code=409, detail="Set up the email account first.")
    if mail_sync.running():
        raise HTTPException(status_code=409, detail="A check is already running.")
    threading.Thread(target=_check, name="mail-check", daemon=True).start()
    result = view()
    result.running = True
    return result
