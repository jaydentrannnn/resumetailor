"""Pay data the student imports from a CSV or XLSX file. Pure parsing, no LLM.

`preview` reads the header and first rows and guesses which column holds each field;
the student confirms or changes that mapping, then `save` imports with it. A row needs a
role, a currency, a pay period and either a low and high or a median; a row missing any
of them is rejected with the reason, never guessed. Periods are kept as stated (hour,
week, month, year) and never converted.

Datasets are app-wide (`DATA_ROOT/pay_data/<id>.json`): market data is not tied to a
profile. Each keeps its name, the source the student gave, an "as of" date, when it was
imported and how many rows were rejected.
"""

from __future__ import annotations

import csv
import io
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.infra import atomic

from .pay_parse import Currency, Period

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000
#: Rows shown in the preview, and rejected rows kept as examples.
SAMPLE_ROWS = 8

FieldName = Literal[
    "company", "role", "level", "location", "currency", "period", "low", "high", "median",
    "sample_size", "source", "as_of",
]
FIELDS: tuple[FieldName, ...] = (
    "company", "role", "level", "location", "currency", "period", "low", "high", "median",
    "sample_size", "source", "as_of",
)
_HEADER_WORDS: dict[FieldName, tuple[str, ...]] = {
    "company": ("company", "employer", "organization", "organisation", "firm"),
    "role": ("role", "title", "job title", "position", "job"),
    "level": ("level", "seniority", "grade", "band"),
    "location": ("location", "city", "metro", "region", "state", "office"),
    "currency": ("currency", "ccy"),
    "period": ("period", "pay period", "unit", "frequency", "basis", "pay basis", "per"),
    "low": ("low", "min", "minimum", "from", "salary min", "pay min", "range low"),
    "high": ("high", "max", "maximum", "to", "salary max", "pay max", "range high"),
    "median": ("median", "p50", "mid", "midpoint", "salary", "base salary", "base", "pay",
               "amount", "rate", "wage"),
    "sample_size": ("n", "count", "sample", "sample size", "reports", "respondents"),
    "source": ("source", "dataset", "survey"),
    "as_of": ("as of", "date", "year", "updated", "as_of"),
}
_CURRENCIES: dict[str, Currency] = {
    "usd": "USD", "us$": "USD", "$": "USD", "cad": "CAD", "c$": "CAD", "ca$": "CAD",
    "gbp": "GBP", "£": "GBP", "eur": "EUR", "€": "EUR", "aud": "AUD", "a$": "AUD",
    "au$": "AUD",
}
_PERIODS: dict[Period, re.Pattern[str]] = {
    "hour": re.compile(r"^(?:per )?(?:hour|hourly|hr|h)$"),
    "week": re.compile(r"^(?:per )?(?:week|weekly|wk)$"),
    "month": re.compile(r"^(?:per )?(?:month|monthly|mo)$"),
    "year": re.compile(r"^(?:per )?(?:year|yearly|annual|annually|annum|yr|y|salary)$"),
}
_LOCK = threading.Lock()


class PayRow(BaseModel):
    company: str = ""
    role: str
    level: str = ""
    location: str = ""
    currency: Currency
    period: Period
    low: float | None = None
    high: float | None = None
    median: float | None = None
    sample_size: int | None = None
    source: str = ""
    as_of: str = ""


class Rejected(BaseModel):
    row: int
    reason: str


class Preview(BaseModel):
    columns: list[str]
    #: The guessed column for each field ("" = none).
    mapping: dict[FieldName, str]
    rows: list[list[str]]
    total_rows: int


class Dataset(BaseModel):
    id: str
    name: str
    source: str = ""
    as_of: str = ""
    imported_at: str
    row_count: int
    rejected_count: int
    rejected: list[Rejected] = Field(default_factory=list)
    rows: list[PayRow] = Field(default_factory=list)


class DatasetSummary(BaseModel):
    id: str
    name: str
    source: str
    as_of: str
    imported_at: str
    row_count: int
    rejected_count: int
    rejected: list[Rejected]


class PayFileError(ValueError):
    """The file cannot be read as a table."""


def datasets_dir() -> Path:
    return config.DATA_ROOT / "pay_data"


def _table(filename: str, data: bytes) -> tuple[list[str], list[list[str]]]:
    if len(data) > MAX_BYTES:
        raise PayFileError("The file is over 5 MB.")
    if filename.casefold().endswith(".xlsx"):
        rows = _xlsx_rows(data)
    elif filename.casefold().endswith((".csv", ".txt", ".tsv")):
        rows = _csv_rows(data)
    else:
        raise PayFileError("Import a .csv or .xlsx file.")
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise PayFileError("The file needs a header row and at least one data row.")
    if len(rows) - 1 > MAX_ROWS:
        raise PayFileError(f"The file has more than {MAX_ROWS:,} rows.")
    header = [cell.strip() for cell in rows[0]]
    width = len(header)
    return header, [(row + [""] * width)[:width] for row in rows[1:]]


def _csv_rows(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def _xlsx_rows(data: bytes) -> list[list[str]]:
    import openpyxl  # noqa: PLC0415 - only needed for this one import path

    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many types for a bad file
        raise PayFileError("That is not a readable .xlsx file.") from exc
    try:
        sheet = book.worksheets[0]
        return [["" if v is None else str(v) for v in row]
                for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()


def _guess(header: list[str]) -> dict[FieldName, str]:
    keys = {column: " ".join(re.findall(r"[a-z0-9$£€]+", column.casefold())) for column in header}
    mapping: dict[FieldName, str] = {}
    used: set[str] = set()
    for name in FIELDS:
        found = next((c for c in header if c not in used and keys[c] in _HEADER_WORDS[name]), "")
        mapping[name] = found
        if found:
            used.add(found)
    return mapping


def preview(filename: str, data: bytes) -> Preview:
    header, rows = _table(filename, data)
    return Preview(columns=header, mapping=_guess(header), rows=rows[:SAMPLE_ROWS],
                   total_rows=len(rows))


def _amount(text: str) -> float | None:
    cleaned = re.sub(r"[\s$£€,]|USD|CAD|GBP|EUR|AUD", "", text.strip(), flags=re.I)
    scale = 1000 if cleaned.casefold().endswith("k") else 1
    try:
        value = float(cleaned.rstrip("kK")) * scale
    except ValueError:
        return None
    return value if value > 0 else None


def _currency(text: str) -> Currency | None:
    return _CURRENCIES.get(text.strip().casefold())


def _period(text: str) -> Period | None:
    word = text.strip().casefold().lstrip("/")
    return next((p for p, pattern in _PERIODS.items() if pattern.match(word)), None)


def _row(cells: dict[FieldName, str]) -> PayRow | str:
    """A valid row, or why it was rejected."""
    if not cells.get("role", "").strip():
        return "No role or title."
    currency = _currency(cells.get("currency", ""))
    if currency is None:
        return "No currency (USD, CAD, GBP, EUR or AUD)."
    period = _period(cells.get("period", ""))
    if period is None:
        return "No pay period (hour, week, month or year)."
    low, high, median = (_amount(cells.get(k, "")) for k in ("low", "high", "median"))
    if median is None and (low is None or high is None):
        return "Needs a low and a high, or a median."
    if low is not None and high is not None and high < low:
        return "The high is below the low."
    size = _amount(cells.get("sample_size", ""))
    return PayRow(
        company=cells.get("company", "").strip(), role=cells["role"].strip(),
        level=cells.get("level", "").strip(), location=cells.get("location", "").strip(),
        currency=currency, period=period, low=low, high=high, median=median,
        sample_size=int(size) if size else None, source=cells.get("source", "").strip(),
        as_of=cells.get("as_of", "").strip()[:10],
    )


def read_rows(
    filename: str, data: bytes, mapping: dict[FieldName, str]
) -> tuple[list[PayRow], list[Rejected], int]:
    """Rows read with ``mapping``, the rejected ones (first few) and the rejected count."""
    header, rows = _table(filename, data)
    index = {name: header.index(column) for name, column in mapping.items()
             if column and column in header}
    kept: list[PayRow] = []
    rejected: list[Rejected] = []
    count = 0
    for number, row in enumerate(rows, start=2):
        found = _row({name: row[i] for name, i in index.items()})
        if isinstance(found, PayRow):
            kept.append(found)
            continue
        count += 1
        if len(rejected) < SAMPLE_ROWS:
            rejected.append(Rejected(row=number, reason=found))
    return kept, rejected, count


def save(
    filename: str, data: bytes, mapping: dict[FieldName, str], *, name: str = "",
    source: str = "", as_of: str = "",
) -> Dataset:
    kept, rejected, count = read_rows(filename, data, mapping)
    if not kept:
        raise PayFileError("No row had a role, currency, pay period and pay figures.")
    dataset = Dataset(
        id=uuid.uuid4().hex[:12], name=(name or Path(filename).stem)[:120],
        source=source[:200], as_of=as_of[:10],
        imported_at=datetime.now(UTC).isoformat(timespec="seconds"),
        row_count=len(kept), rejected_count=count, rejected=rejected, rows=kept,
    )
    with _LOCK:
        target = datasets_dir() / f"{dataset.id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_text(target, dataset.model_dump_json() + "\n")
    return dataset


def load_all() -> list[Dataset]:
    folder = datasets_dir()
    if not folder.is_dir():
        return []
    found = [atomic.read_cached(path, Dataset) for path in sorted(folder.glob("*.json"))]
    return sorted((d for d in found if d is not None), key=lambda d: d.imported_at, reverse=True)


def summaries() -> list[DatasetSummary]:
    return [DatasetSummary(**d.model_dump(exclude={"rows"})) for d in load_all()]


def delete(dataset_id: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{12}", dataset_id):
        return False
    with _LOCK:
        path = datasets_dir() / f"{dataset_id}.json"
        if not path.is_file():
            return False
        path.unlink()
    return True
