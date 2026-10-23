"""Posted pay ranges read from posting text (`research/pay_parse.py`)."""

from __future__ import annotations

import pytest

from resume_tailor.research.pay_parse import posted_ranges


def _one(text):
    found = posted_ranges(text)
    assert len(found) == 1, found
    r = found[0]
    return r.low, r.high, r.currency, r.period, r.period_stated


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The base pay range for this role is $120,000 - $150,000 per year.",
         (120000, 150000, "USD", "year", True)),
        ("Pay: $25/hr - $30/hr", (25, 30, "USD", "hour", True)),
        ("Salary: £30,000 - £35,000 p.a.", (30000, 35000, "GBP", "year", True)),
        ("CA$70,000 – CA$85,000 annually", (70000, 85000, "CAD", "year", True)),
        ("€50.000 - €60.000 per year", (50000, 60000, "EUR", "year", True)),
        ("A$95,000 plus super", (95000, 95000, "AUD", "year", False)),
        ("The weekly pay range for this role is:\n\n$1,850 — $2,250 USD",
         (1850, 2250, "USD", "week", True)),
        ("between $4,000 and $6,000 per month", (4000, 6000, "USD", "month", True)),
        ("$60-80k", (60000, 80000, "USD", "year", False)),
        ("USD 90,000 - 110,000", (90000, 110000, "USD", "year", False)),
        ("Starting Pay / Salary Range £2.625,00 / month", (2625, 2625, "GBP", "month", True)),
    ],
)
def test_currencies_and_periods_are_read_as_stated(text, expected):
    assert _one(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "We raised $50 million in our Series B.",
        "Sign-on bonus of $5,000.",
        "Earn $0.60 per mile.",
        "We offer a $6,000 Intern Stipend to help cover your temporary housing.",
        "Base Pay Range: $0.00 - $0.00",
        "$12,000 for 10 weeks",
    ],
)
def test_figures_that_are_not_base_pay_are_skipped(text):
    assert posted_ranges(text) == []


def test_salary_is_not_a_period_word():
    # Hourly figures in a "salary range" stay hourly; the word salary says nothing.
    assert _one("Estimated Starting Salary Range: $23.54 - $32.37.") == (
        23.54, 32.37, "USD", "hour", False)


def test_a_minimum_and_maximum_on_one_line_are_one_range():
    text = "Compensation Minimum: $25.00 Compensation Maximum: $39.00 The intern will..."
    assert _one(text) == (25, 39, "USD", "hour", False)


def test_a_worded_period_the_figure_cannot_be_gives_way_to_its_size():
    text = "Compensation Details: $145,000 - $195,000 The compensation range or hourly rate..."
    assert _one(text)[:4] == (145000, 195000, "USD", "year")


def test_each_range_is_kept_once_with_its_sentence():
    text = ("Pay is $27/hour. Benefits apply.\nPay is $27/hour.\n"
            "For Toronto, the range is $125,320 - $142,783 CAD.")
    found = posted_ranges(text)
    assert [(r.low, r.currency) for r in found] == [(27, "USD"), (125320, "CAD")]
    assert found[1].excerpt == "For Toronto, the range is $125,320 - $142,783 CAD"


def test_a_second_number_that_is_not_a_top_leaves_the_first_alone():
    assert _one("Salary $50,000 and 401(k) match")[:2] == (50000, 50000)
