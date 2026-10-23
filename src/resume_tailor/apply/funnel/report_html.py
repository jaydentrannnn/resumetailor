"""The application report: one self-contained HTML file to keep or share offline.

Pure over the registry rows: no network, no LLM, no external assets. Styles and charts
are inline (CSS and SVG) and every value is escaped. Each rate is shown as a count over
a stated denominator. Silence ("no reply yet", or marked "no reply") is never counted
as a rejection, and a stage reached before a rejection still counts as reached.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape

from . import outcomes, store_models, store_stats

#: Prepared but not sent: tailored and waiting on a fill or on the applicant.
_PREPARED = frozenset({"ready", "filling", "awaiting_review", "awaiting_otp", "fill_failed"})
#: Weeks of sends the bar chart shows.
_WEEKS = 26

EVENT_LABELS: dict[str, str] = {
    "assessment": "Assessment or test",
    "interview_invited": "Invited to interview",
    "interview_scheduled": "Interview scheduled",
    "interview_completed": "Interview done",
    "offer": "Offer",
    "hired": "Hired",
    "offer_declined": "Declined the offer",
    "rejected": "Rejected",
    "withdrawn": "Withdrew",
    "ghosted": "No reply",
    "employer_timeline": "Employer gave a timeline",
    "followup_drafted": "Follow-up drafted",
    "followup_sent": "Follow-up sent",
}
_HOW = {"app": "Sent by the app", "hand": "Marked by hand", "unconfirmed": "Not confirmed"}
#: The funnel's steps: each counts applications that got this far *or further*. An
#: assessment is left out, since an interview without one would still count through it.
FUNNEL: tuple[tuple[str, str], ...] = (
    ("applied", "Sent"), ("interview", "Interviewed"), ("offer", "Offer"), ("hired", "Hired"),
)


@dataclass
class SentRow:
    company: str
    role: str
    source: str
    ats: str
    sent_on: str
    #: "app" (the app uploaded and sent it), "hand" (marked sent) or "unconfirmed".
    how: str
    progress: outcomes.HiringProgress
    last_event: str = ""
    last_event_on: str = ""


@dataclass
class Breakdown:
    sent: int = 0
    responded: int = 0
    interviewed: int = 0


@dataclass
class ReportData:
    today: str
    found: int
    prepared: int
    sent: list[SentRow]
    cohort: store_stats.OutcomeCohort
    #: Funnel step -> sent applications that ever got that far or further (all sent,
    #: not just the cohort).
    reached: dict[str, int]
    rejected: int
    marked_no_reply: int
    no_reply_yet: int
    by_source: dict[str, Breakdown] = field(default_factory=dict)
    by_ats: dict[str, Breakdown] = field(default_factory=dict)
    #: Monday (ISO date) -> applications sent that week, oldest first.
    weekly: list[tuple[str, int]] = field(default_factory=list)


def _how(app: store_models.Application) -> str:
    if app.status == "submit_unconfirmed":
        return "unconfirmed"
    live = [a for a in app.attempts if a.voided_at is None]
    return "app" if any(a.confirmed for a in live) else "hand"


def _last_event(app: store_models.Application) -> tuple[str, str]:
    events = outcomes.live_events(app)
    if not events:
        return "", ""
    last = max(events, key=lambda e: (e.occurred_on or e.recorded_at[:10], e.recorded_at))
    return EVENT_LABELS.get(last.type, last.type), last.occurred_on or last.recorded_at[:10]


def _rank(progress: outcomes.HiringProgress) -> int:
    return outcomes.STAGES.index(progress.stage or "applied")


def _weekly(rows: list[SentRow], today: date) -> list[tuple[str, int]]:
    monday = today - timedelta(days=today.weekday())
    weeks = [(monday - timedelta(weeks=n)).isoformat() for n in range(_WEEKS - 1, -1, -1)]
    counts: Counter[str] = Counter()
    for row in rows:
        try:
            sent = date.fromisoformat(row.sent_on)
        except ValueError:
            continue
        counts[(sent - timedelta(days=sent.weekday())).isoformat()] += 1
    return [(week, counts[week]) for week in weeks]


def summarize(
    apps: Iterable[store_models.Application], *, today: date | None = None
) -> ReportData:
    """Count the registry for the report (archived rows included)."""
    today = today or date.today()
    apps = list(apps)
    sent: list[SentRow] = []
    for app in apps:
        sent_on = outcomes.sent_on(app)
        if not sent_on:
            continue
        label, on = _last_event(app)
        sent.append(SentRow(
            company=app.company, role=app.role, source=app.source, ats=app.ats,
            sent_on=sent_on, how=_how(app), progress=outcomes.hiring_progress(app),
            last_event=label, last_event_on=on,
        ))
    sent.sort(key=lambda row: row.sent_on, reverse=True)
    interview = outcomes.STAGES.index("interview")
    by_source: dict[str, Breakdown] = {}
    by_ats: dict[str, Breakdown] = {}
    for row in sent:
        for table, key in ((by_source, row.source or "unknown"), (by_ats, row.ats)):
            item = table.setdefault(key, Breakdown())
            item.sent += 1
            item.responded += row.progress.responded
            item.interviewed += _rank(row.progress) >= interview
    return ReportData(
        today=today.isoformat(),
        found=len(apps),
        prepared=sum(
            app.status in _PREPARED and not outcomes.sent_on(app) and not app.archived_at
            for app in apps
        ),
        sent=sent,
        cohort=store_stats.outcome_cohort(apps, today=today),
        reached={
            stage: sum(_rank(row.progress) >= outcomes.STAGES.index(stage) for row in sent)
            for stage, _label in FUNNEL
        },
        rejected=sum(row.progress.closed == "rejected" for row in sent),
        marked_no_reply=sum(row.progress.closed == "ghosted" for row in sent),
        no_reply_yet=sum(
            not row.progress.responded and row.progress.closed is None for row in sent
        ),
        by_source=dict(sorted(by_source.items(), key=lambda kv: -kv[1].sent)),
        by_ats=dict(sorted(by_ats.items(), key=lambda kv: -kv[1].sent)),
        weekly=_weekly(sent, today),
    )


# -- rendering --------------------------------------------------------------------------

_CSS = """
:root{--paper:#fff;--panel:#f7f7f6;--line:#e2e2df;--ink:#0b0b0b;--muted:#6b6b68;
--accent:#1f6b4a;--bar:#1f6b4a}
@media (prefers-color-scheme:dark){:root{--paper:#0a0a0a;--panel:#151515;--line:#2a2a2a;
--ink:#f5f5f4;--muted:#8f8f8c;--accent:#6fbf98;--bar:#6fbf98}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 48px}
h1{font:600 26px/1.2 Georgia,"Times New Roman",serif;margin:0 0 4px}
h2{font-size:15px;margin:32px 0 10px}
.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:12px}
.card b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
.card span{color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600}
.scroll{overflow-x:auto}
svg{display:block;max-width:720px}
svg text{fill:var(--ink);font-size:12px}
svg .bar{fill:var(--bar)}
svg .track{fill:var(--panel);stroke:var(--line)}
@media print{body{background:#fff;color:#000}main{padding:0}.card{break-inside:avoid}
tr{break-inside:avoid}}
"""


def _pct(part: int, whole: int) -> str:
    return f"{part} of {whole} ({round(100 * part / whole)}%)" if whole else f"{part} of 0"


def _card(value: int | str, label: str) -> str:
    return f'<div class="card"><b>{escape(str(value))}</b><span>{escape(label)}</span></div>'


def _cards(data: ReportData) -> str:
    how = Counter(row.how for row in data.sent)
    cohort = data.cohort
    window = f"sent {cohort.window_days}+ days ago"
    items = [
        _card(len(data.sent), "Sent in all"),
        _card(how["app"], _HOW["app"]),
        _card(how["hand"], _HOW["hand"]),
        _card(how["unconfirmed"], "Sent, not confirmed"),
        _card(data.prepared, "Prepared, not sent yet"),
        _card(_pct(cohort.responded, cohort.sent), f"Replied, of those {window}"),
        _card(_pct(cohort.interviewed, cohort.sent), f"Interviewed, of those {window}"),
        _card(_pct(cohort.offers, cohort.sent), f"Offers, of those {window}"),
        _card(data.rejected, "Rejected (the employer said no)"),
        _card(data.no_reply_yet, "No reply yet"),
        _card(data.marked_no_reply, "Marked as no reply"),
    ]
    return f'<div class="cards">{"".join(items)}</div>'


def _funnel(data: ReportData) -> str:
    total = len(data.sent)
    width, row_h, label_w = 640, 28, 120
    rows = []
    for i, (stage, label) in enumerate(FUNNEL):
        count = data.reached[stage]
        y = i * row_h
        bar = 0 if not total else round((width - label_w - 150) * count / total)
        rows.append(
            f'<text x="0" y="{y + 18}">{escape(label)}</text>'
            f'<rect class="track" x="{label_w}" y="{y + 4}" width="{width - label_w - 150}" '
            f'height="18" rx="2"/>'
            f'<rect class="bar" x="{label_w}" y="{y + 4}" width="{bar}" height="18" rx="2"/>'
            f'<text x="{width - 140}" y="{y + 18}">{escape(_pct(count, total))}</text>'
        )
    height = row_h * len(FUNNEL)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Furthest stage reached">{"".join(rows)}</svg>'
    )


def _weekly_chart(data: ReportData) -> str:
    if not data.weekly:
        return ""
    peak = max(count for _, count in data.weekly) or 1
    width, height, gap = 640, 120, 4
    step = width / len(data.weekly)
    bars = []
    for i, (week, count) in enumerate(data.weekly):
        h = round((height - 20) * count / peak)
        x = round(i * step, 1)
        bars.append(
            f'<rect class="bar" x="{x}" y="{height - 16 - h}" width="{round(step - gap, 1)}" '
            f'height="{h}"><title>{escape(f"Week of {week}: {count} sent")}</title></rect>'
        )
    first, last = data.weekly[0][0], data.weekly[-1][0]
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Applications sent per week">{"".join(bars)}'
        f'<text x="0" y="{height - 2}">{escape(first)}</text>'
        f'<text x="{width}" y="{height - 2}" text-anchor="end">{escape(last)}</text></svg>'
    )


def _breakdown(title: str, table: dict[str, Breakdown]) -> str:
    if not table:
        return ""
    body = "".join(
        f"<tr><td>{escape(key)}</td><td>{item.sent}</td>"
        f"<td>{escape(_pct(item.responded, item.sent))}</td>"
        f"<td>{escape(_pct(item.interviewed, item.sent))}</td></tr>"
        for key, item in table.items()
    )
    return (
        f'<h2>{escape(title)}</h2><div class="scroll"><table><thead><tr><th></th>'
        f"<th>Sent</th><th>Replied</th><th>Interviewed</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _sent_table(data: ReportData) -> str:
    if not data.sent:
        return '<p class="muted">Nothing has been sent yet.</p>'
    body = "".join(
        "<tr>"
        f"<td>{escape(row.company)}</td><td>{escape(row.role)}</td>"
        f"<td>{escape(row.sent_on)}</td><td>{escape(_HOW[row.how])}</td>"
        f"<td>{escape(outcomes.STAGE_LABELS[row.progress.stage or 'applied'])}</td>"
        f"<td>{escape(outcomes.STAGE_LABELS[row.progress.closed]) if row.progress.closed else ''}"
        f"</td><td>{escape(row.last_event)}"
        f"{' · ' + escape(row.last_event_on) if row.last_event_on else ''}</td>"
        "</tr>"
        for row in data.sent
    )
    return (
        '<div class="scroll"><table><thead><tr><th>Company</th><th>Role</th><th>Sent</th>'
        "<th>How</th><th>Furthest stage</th><th>Closed</th><th>Last event</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def render(data: ReportData, *, profile: str = "") -> str:
    """The whole report as one HTML document."""
    who = f" · {escape(profile)}" if profile else ""
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Application report {escape(data.today)}</title><style>{_CSS}</style>"
        "</head><body><main>"
        f"<h1>Application report</h1><p class=\"muted\">Made {escape(data.today)}{who}. "
        f"{data.found} postings found in all. Reply, interview and offer rates count only "
        f"applications sent at least {data.cohort.window_days} days ago, so recent ones "
        "have had time to hear back. Silence is never counted as a rejection.</p>"
        f"{_cards(data)}"
        "<h2>Furthest stage reached</h2><p class=\"muted\">Of everything sent. An "
        "application that reached an interview and was then rejected still counts as "
        "interviewed.</p>"
        f"{_funnel(data)}"
        "<h2>Sent per week</h2>"
        f"{_weekly_chart(data)}"
        f"{_breakdown('By source', data.by_source)}"
        f"{_breakdown('By application system', data.by_ats)}"
        "<h2>Everything sent</h2>"
        f"{_sent_table(data)}"
        "</main></body></html>"
    )


def build(
    apps: Iterable[store_models.Application], *, today: date | None = None, profile: str = ""
) -> str:
    return render(summarize(apps, today=today), profile=profile)
