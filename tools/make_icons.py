#!/usr/bin/env python3
"""Иконки приложений. Рисуются кодом, чтобы не тащить бинарники в репозиторий
и чтобы их можно было поменять одной строкой.

    python3 tools/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "icons"

# Приложение → фон, цвет знака, знак.
APPS = {
    "waiter": ("#100f0d", "#d9945c", "З"),
    "station": ("#100f0d", "#4fae7d", "Б"),
    "admin": ("#100f0d", "#6ba7d6", "А"),
}
SIZES = (192, 512)


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def draw(name: str, bg: str, ink: str, glyph: str, size: int) -> None:
    img = Image.new("RGB", (size, size), bg)
    pen = ImageDraw.Draw(img)
    pad = size // 12
    pen.rounded_rectangle(
        (pad, pad, size - pad, size - pad), radius=size // 5, outline=ink, width=size // 28
    )
    f = font(int(size * 0.44))
    box = pen.textbbox((0, 0), glyph, font=f)
    pen.text(
        ((size - box[2] - box[0]) / 2, (size - box[3] - box[1]) / 2),
        glyph,
        font=f,
        fill=ink,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}-{size}.png")


def main() -> None:
    for name, (bg, ink, glyph) in APPS.items():
        for size in SIZES:
            draw(name, bg, ink, glyph, size)
    print("иконки в", OUT)


if __name__ == "__main__":
    main()
