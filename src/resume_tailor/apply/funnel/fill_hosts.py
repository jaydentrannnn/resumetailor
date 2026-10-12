"""One fill per Workday site at a time, for parallel Fill batches.

Parallel fills share the browser and the per-site Workday account. Two fills on one new
site both saw "no account", both pressed Create Account, and the second hit "already
exists"; their vault writes also collided. The dispatcher now takes the next pending
application whose Workday site is not already being filled, so different sites still run
side by side while same-site applications run one after another (2026-10-12).

A site whose account is waiting for email verification is also remembered: the rest of
the batch on that site is handed back at once instead of spending a Sign In attempt that
can only fail until the applicant clicks the verification link.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from resume_tailor.apply.ats import workday_auth
from resume_tailor.apply.funnel import store, store_models


def workday_host(app: store_models.Application | None) -> str:
    """The Workday site an application fills on, or "" when it is not a Workday form."""
    if app is None:
        return ""
    url = app.final_url or app.posting_url
    if app.ats != "workday" and not workday_auth.is_workday_url(url):
        return ""
    return workday_auth.extract_workday_tenant(url)


class HostGate:
    """Tracks which Workday sites are busy or waiting for email verification.

    Not thread-safe on its own: callers hold the dispatcher's lock around every call.
    """

    def __init__(
        self, lookup: Callable[[str], store_models.Application | None] | None = None
    ) -> None:
        # Looked up at call time so tests that patch ``store.get`` reach the gate too.
        self._lookup = lookup or (lambda application_id: store.get(application_id))
        self._hosts: dict[str, str] = {}
        self.busy: set[str] = set()
        #: site -> label of the application whose account awaits email verification.
        self.awaiting_verification: dict[str, str] = {}

    def host(self, application_id: str) -> str:
        if application_id not in self._hosts:
            self._hosts[application_id] = workday_host(self._lookup(application_id))
        return self._hosts[application_id]

    def take(self, pending: deque[str]) -> str | None:
        """Pop the first pending id whose site is free; None while every one is busy."""
        for index, application_id in enumerate(pending):
            host = self.host(application_id)
            if host and host in self.busy:
                continue
            del pending[index]
            if host:
                self.busy.add(host)
            return application_id
        return None

    def release(self, application_id: str) -> None:
        self.busy.discard(self.host(application_id))

    def record_result(self, application_id: str, label: str) -> None:
        """Remember a site whose account now waits for the applicant's email link."""
        host = self.host(application_id)
        app = self._lookup(application_id)
        if host and app is not None and app.status == "awaiting_otp":
            self.awaiting_verification.setdefault(host, label)

    def verification_hold(self, application_id: str) -> str:
        """Why this application must wait for an earlier one's email verification, or ""."""
        host = self.host(application_id)
        earlier = self.awaiting_verification.get(host, "") if host else ""
        if not earlier:
            return ""
        return (
            f"Workday account on {host} is waiting for email verification ({earlier}). "
            "Click the link in Workday's email, then Fill this application again."
        )
