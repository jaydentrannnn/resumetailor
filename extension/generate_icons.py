"""Create the extension's PNG icons: a racing-green page on a black square.

Drawn at 8x and downscaled, so the small sizes stay crisp. The 32px design grid
and mark match desktop/app-icon.svg, including its 4px corner radius.

    python extension/generate_icons.py              # icons/icon{16,32,48,128}.png
    python extension/generate_icons.py --size 300   # also store/logo300.png (Edge)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
INK = (11, 11, 11, 255)
GREEN = (31, 107, 74, 255)
SCALE = 8


def draw(size: int) -> Image.Image:
    big = size * SCALE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    unit = big / 32  # design grid: 32 x 32

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (round(x0 * unit), round(y0 * unit), round(x1 * unit), round(y1 * unit))

    pen.rounded_rectangle(box(0, 0, 32, 32), radius=round(4 * unit), fill=INK)
    # The page, with a folded top-right corner.
    pen.polygon(
        [(9 * unit, 6 * unit), (19 * unit, 6 * unit), (23 * unit, 10 * unit),
         (23 * unit, 26 * unit), (9 * unit, 26 * unit)],
        fill=GREEN,
    )
    pen.polygon([(19 * unit, 6 * unit), (19 * unit, 10 * unit), (23 * unit, 10 * unit)], fill=INK)
    for x0, y, x1 in ((12, 12, 20), (12, 16, 18)):
        pen.rectangle(box(x0, y, x1, y + 1.6), fill=INK)
    pen.line(
        [(12 * unit, 21 * unit), (15 * unit, 24 * unit), (20 * unit, 19 * unit)],
        fill=INK, width=round(1.8 * unit), joint="curve",
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
