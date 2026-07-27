"""Compare Word-rendered PDFs against LibreOffice-rendered PDFs of the same .docx.

Phase 0 gate for containerising the tool (see docs/PLAN.md). The fit loop decides overflow
on `page_count` and underflow on `line_count`, both read off a rendered PDF — so swapping
Word for LibreOffice is only safe if those two numbers agree, or disagree by a knowable
constant that re-calibration can absorb.

`output/` already holds Word-rendered .docx/.pdf pairs from earlier runs. This script
compares each against a LibreOffice rendering of the same .docx, produced separately:

    docker build -f docker/soffice.Dockerfile -t resumetailor-soffice docker
    docker run --rm -v "${PWD}/output:/work" resumetailor-soffice \
        --headless --convert-to pdf --outdir /work/_lo /work/*.docx

    python scripts/compare_pdf_backends.py

It reads no configuration and calls no API: pure measurement over files already on disk.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor import config, render  # noqa: E402


@dataclass
class Comparison:
    """One .docx measured under both rendering engines."""

    name: str
    word_pages: int
    soffice_pages: int
    word_lines: int
    soffice_lines: int

    @property
    def pages_agree(self) -> bool:
        return self.word_pages == self.soffice_pages

    @property
    def line_delta(self) -> int:
        """LibreOffice minus Word. Positive means LibreOffice laid out more lines."""
        return self.soffice_lines - self.word_lines


def _measure(pdf: Path) -> tuple[int, int]:
    """Page and layout-line counts, using the same readers the fit loop uses."""
    return render.page_count(pdf), render.line_count(pdf)


def collect(word_dir: Path, soffice_dir: Path) -> list[Comparison]:
    """Pair every Word PDF with its LibreOffice counterpart and measure both.

    A .docx is skipped (with a note) when either rendering is missing, so a partial
    conversion still produces a usable report rather than an exception.
    """
    results: list[Comparison] = []
    for docx in sorted(word_dir.glob("*.docx")):
        word_pdf = docx.with_suffix(".pdf")
        soffice_pdf = soffice_dir / f"{docx.stem}.pdf"
        if not word_pdf.exists():
            print(f"  skip {docx.name}: no Word PDF beside it")
            continue
        if not soffice_pdf.exists():
            print(f"  skip {docx.name}: no LibreOffice PDF in {soffice_dir}")
            continue

        word_pages, word_lines = _measure(word_pdf)
        soffice_pages, soffice_lines = _measure(soffice_pdf)
        results.append(
            Comparison(
                name=docx.stem,
                word_pages=word_pages,
                soffice_pages=soffice_pages,
                word_lines=word_lines,
                soffice_lines=soffice_lines,
            )
        )
    return results


def report(results: list[Comparison]) -> int:
    """Print the comparison table and a verdict. Returns a process exit code."""
    if not results:
        print("No comparable pairs found.")
        return 1

    width = max(len(r.name) for r in results)
    print(f"\n{'document'.ljust(width)}  {'pages W/LO':>11}  {'lines W/LO':>12}  {'delta':>6}")
    print("-" * (width + 36))
    for r in results:
        flag = "" if r.pages_agree else "  <-- PAGE MISMATCH"
        print(
            f"{r.name.ljust(width)}  "
            f"{f'{r.word_pages}/{r.soffice_pages}':>11}  "
            f"{f'{r.word_lines}/{r.soffice_lines}':>12}  "
            f"{r.line_delta:>+6}{flag}"
        )

    mismatched = [r for r in results if not r.pages_agree]
    deltas = [r.line_delta for r in results]
    worst = max(deltas, key=abs)

    print(f"\n{len(results)} document(s) compared.")
    print(f"Page count agrees on {len(results) - len(mismatched)}/{len(results)}.")
    print(f"Line delta: min {min(deltas):+d}, max {max(deltas):+d}, worst {worst:+d}.")
    print(
        f"\nFit constants currently in use (Word-derived): "
        f"CHARS_PER_LINE={config.CHARS_PER_LINE}, LINES_PER_PAGE={config.LINES_PER_PAGE}"
    )

    if mismatched:
        print(
            "\nVERDICT: engines disagree on page count for "
            f"{', '.join(r.name for r in mismatched)}. LibreOffice is still usable as the "
            "container's measurement engine, but its constants must be re-calibrated "
            "against it rather than inherited from Word."
        )
        return 2

    print(
        "\nVERDICT: page counts agree everywhere. Re-calibrate LINES_PER_PAGE anyway if the "
        "line deltas above are non-zero, since underflow is judged on the line count."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--word-dir",
        type=Path,
        default=config.OUTPUT_DIR,
        help="Directory of .docx files with Word-rendered .pdf siblings.",
    )
    parser.add_argument(
        "--soffice-dir",
        type=Path,
        default=None,
        help="Directory of LibreOffice-rendered PDFs (default: <word-dir>/_lo).",
    )
    args = parser.parse_args()

    soffice_dir = args.soffice_dir or args.word_dir / "_lo"
    if not soffice_dir.exists():
        print(f"error: {soffice_dir} does not exist. Convert with LibreOffice first; see "
              "this script's docstring.", file=sys.stderr)
        return 1

    return report(collect(args.word_dir, soffice_dir))


if __name__ == "__main__":
    raise SystemExit(main())
