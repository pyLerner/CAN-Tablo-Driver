"""Rasterizer for Compact FONT glyph bytecode."""

from __future__ import annotations

from PIL import Image

from .parser import CompactFont

MAX_PAIR_WIDTH = 20


def _mask_pixels(mask: int, y: int, width: int, pixels: dict[tuple[int, int], int]) -> None:
    for bit in range(width):
        if (mask >> (width - 1 - bit)) & 1:
            pixels[(bit, y)] = 1


def _expand_rows(row_bits: list[int], height: int) -> list[int]:
    if not row_bits:
        return [0] * height
    rows = [row_bits[0]]
    body = row_bits[1:]
    if body:
        rows.extend(body)
        rev = list(reversed(body))
        while len(rows) < height:
            rows.extend(rev)
    while len(rows) < height:
        rows.append(rows[-1])
    rows = rows[:height]
    if height > 1:
        rows[-1] |= rows[0]
    return rows


def decode_glyph(
    blob: bytes,
    height: int,
    *,
    codepoint: int | None = None,
) -> tuple[Image.Image, int]:
    """
  Decode one glyph bytecode blob into a grayscale image.

    Returns `(image, width)` where the image mode is `L` and uses 0/255 pixels.
    """
    if not blob:
        return Image.new("L", (3, height), 0), 3

    if blob[0] == 0x7E and len(blob) >= 3:
        width = max(1, blob[2])
        return Image.new("L", (width, height), 0), width

    if len(blob) == 3 and blob[1] == 0xFE and blob[2] == 0x01:
        width = max(1, blob[0])
        image = Image.new("L", (width, height), 0)
        x = width // 2
        for y in range(height):
            image.putpixel((x, y), 255)
        return image, width

    if len(blob) == 3 and blob[1] == 0x00:
        width = blob[0] if blob[0] <= 16 else blob[2]
        width = max(1, min(width, 64))
        image = Image.new("L", (width, height), 0)
        x = width // 2
        if codepoint == ord("!"):
            for y in range(max(0, height - blob[2] - 1)):
                image.putpixel((x, y), 255)
            image.putpixel((x, height - 1), 255)
        else:
            image.putpixel((x, height - 1), 255)
        return image, width

    if len(blob) == 3:
        width = max(1, min(blob[2], 64))
        image = Image.new("L", (width, height), 0)
        image.putpixel((width // 2, height - 1), 255)
        return image, width

    parts: list[bytes] = []
    current = bytearray()
    index = 0
    while index < len(blob):
        if index + 1 < len(blob) and blob[index] == 0xFE and blob[index + 1] in (0x00, 0x01):
            parts.append(bytes(current))
            current = bytearray()
            index += 2
        else:
            current.append(blob[index])
            index += 1
    if current:
        parts.append(bytes(current))

    row_bits: list[int] = []
    width = 6
    for part in parts:
        pos = 0
        if pos < len(part) and part[pos] == 0:
            pos += 1

        spans: list[tuple[int, int]] = []
        while pos + 1 < len(part):
            x, span_width = part[pos], part[pos + 1]
            if 0 <= x < 128 and 0 < span_width <= MAX_PAIR_WIDTH:
                spans.append((x, span_width))
                width = max(width, x + span_width)
                pos += 2
            else:
                break

        if spans:
            mask = 0
            row_width = max(width, 8)
            for x, span_width in spans:
                for dx in range(span_width):
                    bit = x + dx
                    mask |= 1 << (row_width - 1 - bit)
            row_bits.append(mask)

        while pos < len(part):
            row_bits.append(part[pos])
            width = max(width, 6, part[pos].bit_length())
            pos += 1

    rows = _expand_rows(row_bits, height)
    pixels: dict[tuple[int, int], int] = {}
    for y, mask in enumerate(rows):
        _mask_pixels(mask, y, width, pixels)

    image = Image.new("L", (width, height), 0)
    for (x, y), _ in pixels.items():
        if 0 <= x < width and 0 <= y < height:
            image.putpixel((x, y), 255)
    return image, width


def render_text(
    font: CompactFont,
    text: str,
    *,
    fg: int = 255,
    bg: int = 0,
    spacing: int = 1,
    missing: str = "?",
) -> Image.Image:
    """Render a UTF-8 string using a parsed Compact font."""

    if not text:
        return Image.new("L", (1, font.height), bg)

    lines = text.splitlines() or [""]
    rendered_lines: list[Image.Image] = []

    for line in lines:
        glyphs: list[Image.Image] = []
        line_width = 0
        for char in line:
            codepoint = ord(char)
            blob = font.glyph_blob(codepoint)
            if blob is None and missing and font.has_codepoint(ord(missing)):
                codepoint = ord(missing)
                blob = font.glyph_blob(codepoint)
            if blob is None:
                continue
            glyph, width = decode_glyph(blob, font.height, codepoint=codepoint)
            if fg != 255 or bg != 0:
                glyph = _recolor(glyph, fg=fg, bg=bg)
            glyphs.append(glyph)
            line_width += width
            if glyphs:
                line_width += spacing
        if glyphs:
            line_width -= spacing
        line_image = Image.new("L", (max(1, line_width), font.height), bg)
        x = 0
        for glyph in glyphs:
            line_image.paste(glyph, (x, 0))
            x += glyph.width + spacing
        rendered_lines.append(line_image)

    total_height = sum(img.height for img in rendered_lines) + max(0, len(rendered_lines) - 1)
    output = Image.new("L", (max(img.width for img in rendered_lines), max(1, total_height)), bg)
    y = 0
    for index, line_image in enumerate(rendered_lines):
        output.paste(line_image, (0, y))
        y += line_image.height
        if index + 1 < len(rendered_lines):
            y += 1
    return output


def _recolor(image: Image.Image, *, fg: int, bg: int) -> Image.Image:
    return image.point(lambda value: fg if value else bg, mode="L")
