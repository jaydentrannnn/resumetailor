"""Every application tab the app closes, keeps or finds gone: logged, and kept on the row.

Tabs are the applicant's work in progress; when one disappears the first question is
whether the app closed it. Each event goes to ``app.log`` and to the row's
``FillResult.tab_history`` (bounded), which the detail page shows.
"""

from __future__ import annotations

import contextlib
import logging
from urllib.parse import urlsplit

from resume_tailor.apply.funnel import store, store_models

_log = logging.getLogger(__name__)
#: Events kept per application, newest last.
KEEP = 10


def entry(application_id: str, event: str, reason: str, *, url: str = "") -> dict[str, str]:
    """Log one tab event (``closed``, ``kept``, ``gone``, ``replaced``); the history entry.
    A fill adds it to its own result (its write replaces the row's), others `record` it."""
    host = urlsplit(url).hostname or ""
    _log.info("tab %s app=%s reason=%s host=%s", event, application_id, reason, host)
    return {"at": store_models._now_iso(), "event": event, "reason": reason, "host": host}


def append(history: list[dict[str, str]], item: dict[str, str]) -> list[dict[str, str]]:
    return [*history, item][-KEEP:]


def record(application_id: str, event: str, reason: str, *, url: str = "") -> None:
    """Log one tab event and keep it on the row (outside a fill); never raises."""
    item = entry(application_id, event, reason, url=url)

    def add(app: store_models.Application) -> None:
        if not app.fill:
            return
        fill = store_models.FillResult.model_validate(app.fill)
        fill.tab_history = append(fill.tab_history, item)
        app.fill = fill

    with contextlib.suppress(Exception):
        store.update(application_id, add)
