"""Create the extension's PNG icons: a page of text on the app's teal, with a check.

Drawn at 8x and downscaled, so the small sizes stay crisp. The 16px icon drops the
check, which would only be a smudge at that size.

    python extension/generate_icons.py              # icons/icon{16,32,48,128}.png
    python extension/generate_icons.py --size 300   # also store/logo300.png (Edge)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
TEAL = (22, 79, 100, 255)
PAPER = (246, 251, 251, 255)
LINE = (22, 79, 100, 255)
ACCENT = (242, 165, 65, 255)
SCALE = 8


def draw(size: int) -> Image.Image:
    big = size * SCALE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    unit = big / 32  # design grid: 32 x 32

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (round(x0 * unit), round(y0 * unit), round(x1 * unit), round(y1 * unit))

    pen.rounded_rectangle(box(1, 1, 31, 31), radius=round(7 * unit), fill=TEAL)
    # The page, with a folded top-right corner.
    pen.polygon(
        [(9 * unit, 6 * unit), (19 * unit, 6 * unit), (23 * unit, 10 * unit),
         (23 * unit, 26 * unit), (9 * unit, 26 * unit)],
        fill=PAPER,
    )
    pen.polygon([(19 * unit, 6 * unit), (19 * unit, 10 * unit), (23 * unit, 10 * unit)], fill=(200, 222, 226, 255))
    lines = ((12, 12, 18), (12, 16, 20), (12, 20, 17)) if size > 16 else ((12, 13, 20), (12, 19, 20))
    thickness = 1.6 if size > 16 else 2.4
    for x0, y, x1 in lines:
        pen.rounded_rectangle(box(x0, y, x1, y + thickness), radius=round(thickness * unit / 2), fill=LINE)
    if size > 16:
        pen.ellipse(box(18, 18, 28, 28), fill=ACCENT, outline=TEAL, width=round(1.2 * unit))
        pen.line(
            [(20.6 * unit, 23.2 * unit), (22.6 * unit, 25.1 * unit), (25.6 * unit, 21 * unit)],
            fill=PAPER, width=round(1.5 * unit), joint="curve",
        )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size", type=int, action="append", default=[], help="extra store logo size")
    args = parser.parse_args()
    icons = HERE / "icons"
    icons.mkdir(exist_ok=True)
    for size in (16, 32, 48, 128):
        draw(size).save(icons / f"icon{size}.png", optimize=True)
    for size in args.size:
        draw(size).save(HERE / "store" / f"logo{size}.png", optimize=True)


if __name__ == "__main__":
    main()
