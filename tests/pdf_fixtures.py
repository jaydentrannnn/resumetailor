"""Tiny synthetic PDFs for the PDF-import tests (no reportlab, no network).

`make_pdf` writes text with the standard Helvetica fonts, whose metrics every PDF
reader knows, so character positions are realistic. Coordinates are from the top-left
of a US-letter page, in points.
"""

from __future__ import annotations

from dataclasses import dataclass

WIDTH, HEIGHT = 612, 792
_FONTS = {"R": "Helvetica", "B": "Helvetica-Bold", "I": "Helvetica-Oblique"}


@dataclass(frozen=True)
class T:
    """One run of text at (x, y from the top)."""

    x: float
    y: float
    text: str
    font: str = "R"
    size: float = 10


def _literal(text: str) -> bytes:
    out = bytearray(b"(")
    for byte in text.encode("cp1252"):
        if byte in (0x28, 0x29, 0x5C):
            out += b"\\" + bytes([byte])
        elif byte < 0x20 or byte > 0x7E:
            out += f"\\{byte:03o}".encode()
        else:
            out.append(byte)
    return bytes(out + b")")


def _stream(runs: list[T], drawing: bytes = b"") -> bytes:
    body = bytearray(drawing)
    for run in runs:
        body += b"BT /" + run.font.encode() + f" {run.size} Tf ".encode()
        body += f"{run.x} {HEIGHT - run.y} Td ".encode() + _literal(run.text) + b" Tj ET\n"
    return bytes(body)


def make_pdf(
    pages: list[list[T]],
    *,
    links: list[tuple[str, tuple[float, float, float, float]]] = (),
    drawing: bytes = b"",
) -> bytes:
    """A PDF with one page per list of runs. `links` go on page one as URI annotations."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_ids = {
        key: add(
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} "
            "/Encoding /WinAnsiEncoding >>".encode()
        )
        for key, name in _FONTS.items()
    }
    fonts = " ".join(f"/{k} {v} 0 R" for k, v in font_ids.items())
    pages_id = len(objects) + 1 + 2 * len(pages) + len(links) + 1
    page_ids = []
    annot_ids = [
        add(
            f"<< /Type /Annot /Subtype /Link /Rect [{r[0]} {HEIGHT - r[3]} {r[2]} {HEIGHT - r[1]}] "
            f"/Border [0 0 0] /A << /S /URI /URI ({uri}) >> >>".encode()
        )
        for uri, r in links
    ]
    for n, runs in enumerate(pages):
        content = _stream(runs, drawing if n == 0 else b"")
        content_id = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        annots = (
            f" /Annots [{' '.join(f'{a} 0 R' for a in annot_ids)}]" if n == 0 and annot_ids else ""
        )
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {WIDTH} {HEIGHT}] "
                f"/Resources << /Font << {fonts} >> >> /Contents {content_id} 0 R{annots} >>".encode()
            )
        )
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    assert add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()) == pages_id

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def single_column_resume() -> bytes:
    """A typical one-column student resume: centred name, contact line, four sections,
    tab-aligned dates on the right, bullets that wrap."""
    runs = [
        T(250, 50, "Alex Doe", "B", 18),
        T(150, 72, "alex@example.com | (555) 010-0000 | Irvine, CA | linkedin.com/in/alexdoe"),
        T(40, 100, "EDUCATION", "B", 11),
        T(40, 116, "University of California, Irvine", "B"),
        T(480, 116, "Expected Jun 2027"),
        T(40, 130, "B.S. Business Economics | GPA: 3.8", "I"),
        T(40, 144, "Relevant Coursework: Corporate Finance, Econometrics, Accounting"),
        T(40, 172, "EXPERIENCE", "B", 11),
        T(40, 188, "Acme Capital", "B"),
        T(470, 188, "Jun 2025 – Aug 2025"),
        T(40, 202, "Summer Analyst", "I"),
        T(510, 202, "New York, NY"),
        T(50, 216, "•"),
        T(62, 216, "Built a discounted cash flow model in Excel for three retail companies and"),
        T(62, 230, "presented the valuation to the deal team"),
        T(50, 244, "•"),
        T(
            62,
            244,
            "Screened 40 comparable companies with Capital IQ, cutting research time by 30%",
        ),
        T(40, 262, "Beta Bank", "B"),
        T(470, 262, "Jan 2025 – May 2025"),
        T(40, 276, "Finance Intern", "I"),
        T(530, 276, "Remote"),
        T(50, 290, "•"),
        T(62, 290, "Reconciled accounts payable for 12 vendors using QuickBooks"),
        T(40, 318, "PROJECTS", "B", 11),
        T(40, 334, "Portfolio Tracker | Python, SQL", "B"),
        T(520, 334, "Mar 2025"),
        T(50, 348, "•"),
        T(62, 348, "Tracked 25 holdings with a Python script and a SQL database"),
        T(40, 376, "SKILLS", "B", 11),
        T(40, 392, "Tools: Excel, Tableau, Bloomberg"),
        T(40, 406, "Languages: Python, SQL, English, Spanish"),
        T(40, 434, "CERTIFICATIONS", "B", 11),
        T(50, 450, "•"),
        T(62, 450, "Bloomberg Market Concepts"),
    ]
    return make_pdf(
        [runs],
        links=[("https://www.linkedin.com/in/alexdoe", (430, 64, 560, 74))],
    )


def two_column_resume() -> bytes:
    """A sidebar design: skills on the left, experience on the right."""
    left = [
        T(40, 60, "Jamie Roe", "B", 16),
        T(40, 80, "jamie@example.com"),
        T(40, 110, "SKILLS", "B", 11),
        T(40, 126, "Excel"),
        T(40, 140, "Tableau"),
        T(40, 154, "SQL"),
        T(40, 168, "Python"),
        T(40, 196, "EDUCATION", "B", 11),
        T(40, 212, "State University", "B"),
        T(40, 226, "B.A. Economics"),
        T(40, 240, "2022 – 2026"),
    ]
    right = [
        T(250, 110, "EXPERIENCE", "B", 11),
        T(250, 126, "Gamma Labs", "B"),
        T(250, 140, "Data Intern, Jun 2025 – Aug 2025", "I"),
        T(260, 154, "•"),
        T(272, 154, "Cleaned 3 sales datasets in SQL for weekly reports"),
        T(260, 168, "•"),
        T(272, 168, "Built a Tableau dashboard used by 5 managers"),
        T(250, 186, "Delta Co", "B"),
        T(250, 200, "Analyst Intern, Jan 2025 – May 2025", "I"),
        T(260, 214, "•"),
        T(272, 214, "Forecast demand for 20 products in Excel"),
    ]
    return make_pdf([left + right])


def image_only_pdf() -> bytes:
    return make_pdf([[]], drawing=b"0.5 g 40 40 500 700 re f\n")
