"""TTF text renderer for fnt-demo."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render_text_ttf(
    font_path: Path,
    pixel_size: int,
    text: str,
    *,
    fg: int = 255,
    bg: int = 0,
    line_gap: int = 1,
) -> Image.Image:
    """
    Render UTF-8 text with a TrueType font into mode ``L``.

    Output is binarized (fg/bg only) for a crisp dot-matrix look.
    """
    if pixel_size < 1:
        raise ValueError("pixel_size must be >= 1")

    font = ImageFont.truetype(str(font_path), pixel_size)

    if not text:
        return Image.new("L", (1, pixel_size), bg)

    lines = text.splitlines() or [""]
    line_images: list[Image.Image] = []
    max_width = 1

    for line in lines:
        if not line:
            line_images.append(Image.new("L", (1, pixel_size), bg))
            continue

        draw_probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        bbox = draw_probe.textbbox((0, 0), line, font=font)
        width = max(1, bbox[2] - bbox[0])
        height = max(1, bbox[3] - bbox[1])
        layer = Image.new("L", (width, height), bg)
        ImageDraw.Draw(layer).text((-bbox[0], -bbox[1]), line, fill=fg, font=font)
        line_images.append(layer)
        max_width = max(max_width, width)

    total_height = sum(img.height for img in line_images)
    if len(line_images) > 1:
        total_height += line_gap * (len(line_images) - 1)

    output = Image.new("L", (max_width, max(1, total_height)), bg)
    y = 0
    for index, line_image in enumerate(line_images):
        output.paste(line_image, (0, y))
        y += line_image.height
        if index + 1 < len(line_images):
            y += line_gap

    if fg != 255 or bg != 0:
        output = output.point(lambda value: fg if value > 127 else bg, mode="L")
    else:
        output = output.point(lambda value: 255 if value > 127 else 0, mode="L")

    return output
