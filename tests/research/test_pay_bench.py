"""Pay for similar roles, grouped and split by currency and period (`research/pay_bench.py`)."""

from __future__ import annotations

from resume_tailor.research import pay_bench


def _fig(low, high, *, company="Other", role="Data Analyst Intern", location="Austin, TX",
         period="hour", currency="USD", app_id=""):
    from resume_tailor.research import pay_level

    return pay_bench.Figure(
        low, high, company, role, location, "2026-09-01", "Saved posting", app_id=app_id,
        family=pay_level.family(role), level=pay_level.level(role), currency=currency,
        period=period,
    )


def _bench(figures, **kw):
    args = {"company": "Acme", "role": "Data Analyst Intern", "location": "Austin, TX",
            "figures": figures, "exclude_app_id": "me"} | kw
    return {g.kind: g for g in pay_bench.benchmark(**args)}


def test_percentiles_need_five_figures_otherwise_the_figures_are_listed():
    few = _bench([_fig(20, 30), _fig(22, 26)])["anywhere"].splits[0]
    assert (few.n, few.median) == (2, None)
    assert [f.point for f in few.figures] == [24, 25]
    many = _bench([_fig(x, x) for x in (20, 22, 24, 26, 28)])["anywhere"].splits[0]
    assert (many.p25, many.median, many.p75, many.figures) == (22, 24, 26, [])


def test_hourly_and_yearly_figures_are_never_mixed():
    groups = _bench([_fig(25, 30), _fig(60000, 70000, period="year"),
                     _fig(30, 34, currency="CAD")])
    splits = {(s.currency, s.period): s.n for s in groups["anywhere"].splits}
    assert splits == {("USD", "hour"): 1, ("USD", "year"): 1, ("CAD", "hour"): 1}


def test_groups_are_same_company_near_and_anywhere_without_the_posting_itself():
    figures = [
        _fig(25, 30, app_id="me", company="Acme"),
        _fig(40, 45, company="Acme Inc.", role="Software Engineer Intern", location="Remote"),
        _fig(20, 24, location="Dallas, TX"),
        _fig(28, 33, location="Seattle, WA"),
        _fig(90000, 99000, role="Senior Data Scientist", period="year"),
    ]
    groups = _bench(figures)
    assert groups["company"].n == 1 and groups["company"].label == "Other roles at Acme"
    # "Near" is the same state, and says so.
    assert groups["near"].n == 1
    assert groups["near"].label == "Intern or co-op, data and machine learning, in TX"
    assert groups["near"].splits[0].figures[0].location == "Dallas, TX"
    assert groups["anywhere"].n == 2
    assert groups["anywhere"].label == "Intern or co-op, data and machine learning, anywhere"


def test_nothing_alike_gives_no_groups():
    assert _bench([_fig(25, 30, role="Mechanical Engineer", period="hour")]) == {}
