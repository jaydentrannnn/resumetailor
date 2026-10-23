"""Pay data imported from CSV and XLSX files (`research/pay_import.py`)."""

from __future__ import annotations

import io

import openpyxl
import pytest

from resume_tailor.research import pay_import

CSV = (
    "Company,Job Title,Level,Location,Currency,Period,Min,Max,Median,N,As of\n"
    "Acme,Data Analyst Intern,Intern,\"Austin, TX\",USD,hourly,24,30,,12,2026-09-01\n"
    "Globex,Data Analyst,,Remote,usd,year,,,85000,40,2026-08-01\n"
    "Hooli,Data Analyst Intern,,\"Austin, TX\",,hour,25,31,,,\n"
    "Initech,Data Analyst Intern,,\"Austin, TX\",USD,biweekly,25,31,,,\n"
    "Umbrella,Data Analyst Intern,,\"Austin, TX\",GBP,hour,,,,,\n"
)


def test_the_preview_guesses_columns_and_saves_nothing():
    found = pay_import.preview("survey.csv", CSV.encode())
    assert found.total_rows == 5
    assert (found.mapping["role"], found.mapping["low"], found.mapping["high"]) == (
        "Job Title", "Min", "Max")
    assert (found.mapping["median"], found.mapping["sample_size"]) == ("Median", "N")
    assert found.mapping["source"] == ""
    assert pay_import.load_all() == []


def test_rows_without_currency_period_or_pay_are_rejected_with_a_reason():
    mapping = pay_import.preview("survey.csv", CSV.encode()).mapping
    saved = pay_import.save("survey.csv", CSV.encode(), mapping, source="Campus survey")
    assert (saved.row_count, saved.rejected_count) == (2, 3)
    assert [(r.row, r.reason) for r in saved.rejected] == [
        (4, "No currency (USD, CAD, GBP, EUR or AUD)."),
        (5, "No pay period (hour, week, month or year)."),
        (6, "Needs a low and a high, or a median."),
    ]
    acme, globex = saved.rows
    assert (acme.low, acme.high, acme.period, acme.sample_size) == (24, 30, "hour", 12)
    assert (globex.median, globex.currency, globex.period) == (85000, "USD", "year")
    assert [d.name for d in pay_import.summaries()] == ["survey"]
    assert pay_import.delete(saved.id) and pay_import.load_all() == []


def test_an_xlsx_file_imports_like_a_csv():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Role", "Currency", "Pay period", "Low", "High"])
    sheet.append(["Software Engineer Intern", "CAD", "hour", 30, 38])
    sheet.append(["Software Engineer Intern", "CAD", None, 30, 38])
    buffer = io.BytesIO()
    book.save(buffer)
    data = buffer.getvalue()
    mapping = pay_import.preview("pay.xlsx", data).mapping
    saved = pay_import.save("pay.xlsx", data, mapping)
    assert [(r.currency, r.period, r.low, r.high) for r in saved.rows] == [
        ("CAD", "hour", 30, 38)]
    assert saved.rejected_count == 1


def test_a_file_that_is_not_a_table_is_refused():
    with pytest.raises(pay_import.PayFileError):
        pay_import.preview("notes.pdf", b"%PDF-1.7")
    with pytest.raises(pay_import.PayFileError):
        pay_import.preview("pay.xlsx", b"not a zip")
    with pytest.raises(pay_import.PayFileError):
        pay_import.preview("one.csv", b"Role,Currency\n")
