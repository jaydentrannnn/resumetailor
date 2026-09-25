"""Create the extension's plain geometric PNG icons."""

from pathlib import Path

from PIL import Image, ImageDraw

root = Path(__file__).parent / "icons"
root.mkdir(exist_ok=True)
for size in (16, 32, 48, 128):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, size // 12)
    draw.rounded_rectangle(
        (margin, margin, size - margin - 1, size - margin - 1),
        radius=size // 5,
        fill="#164f64",
    )
    for index, width in enumerate((0.52, 0.43, 0.5)):
        y = int(size * (0.34 + index * 0.16))
        draw.rounded_rectangle(
            (int(size * 0.25), y, int(size * (0.25 + width)), y + max(1, size // 18)),
            radius=max(1, size // 36),
            fill="#ecf8f7",
        )
    image.save(root / f"icon{size}.png")
