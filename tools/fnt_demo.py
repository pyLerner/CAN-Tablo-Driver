#!/usr/bin/env python3
"""Render stdin text and save a JPEG preview (TTF or native Compact .fnt)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from compact_fnt import font_path_for_index, load_fnt, render_text
from compact_fnt.catalog import FNT_INDEX_TO_HEIGHT, VALID_FNT_INDEXES
from compact_fnt.ttf_catalog import default_ttf_path, pixel_size_for_index
from compact_fnt.ttf_render import render_text_ttf
from PIL import Image


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render UTF-8 text from stdin. "
            "Default backend uses Advanced Dot Digital-7 TTF (Latin + Cyrillic); "
            "native backend uses experimental Compact .fnt bytecode decoding."
        ),
    )
    parser.add_argument(
        "--fnt-index",
        type=int,
        required=True,
        choices=VALID_FNT_INDEXES,
        help="Font preset: native .fnt id, or TTF pixel height (62=8px .. 69=40px).",
    )
    parser.add_argument(
        "--backend",
        choices=("ttf", "native"),
        default="ttf",
        help="ttf: Advanced Dot Digital-7 (default); native: Compact .fnt bytecode.",
    )
    parser.add_argument(
        "--font-path",
        type=Path,
        default=None,
        help="Override TTF path (ttf backend only; default: bundled Advanced Dot Digital-7).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="fnt-demo.jpg",
        help="Output JPEG path (default: fnt-demo.jpg).",
    )
    parser.add_argument(
        "--fg",
        type=int,
        default=255,
        help="Foreground brightness 0..255 (default: 255).",
    )
    parser.add_argument(
        "--bg",
        type=int,
        default=0,
        help="Background brightness 0..255 (default: 0).",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=4,
        help="Padding around the rendered text in pixels (default: 4).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not 0 <= args.fg <= 255 or not 0 <= args.bg <= 255:
        raise SystemExit("--fg and --bg must be in range 0..255")
    if args.padding < 0:
        raise SystemExit("--padding must be >= 0")

    text = sys.stdin.buffer.read().decode("utf-8")

    if args.backend == "ttf":
        font_path = args.font_path if args.font_path is not None else default_ttf_path()
        if not font_path.is_file():
            raise SystemExit(f"TTF font not found: {font_path}")
        pixel_size = pixel_size_for_index(args.fnt_index)
        rendered = render_text_ttf(
            font_path,
            pixel_size,
            text,
            fg=args.fg,
            bg=args.bg,
        )
    else:
        fnt_path = font_path_for_index(args.fnt_index)
        font = load_fnt(fnt_path, expected_font_id=args.fnt_index)
        expected_height = FNT_INDEX_TO_HEIGHT[args.fnt_index]
        if font.height != expected_height:
            raise SystemExit(
                f"Font height mismatch: {font.height} in file, expected {expected_height}"
            )
        rendered = render_text(font, text, fg=args.fg, bg=args.bg)

    pad = args.padding
    canvas = Image.new(
        "L",
        (rendered.width + 2 * pad, rendered.height + 2 * pad),
        args.bg,
    )
    canvas.paste(rendered, (pad, pad))
    output_path = Path(args.output)
    canvas.convert("RGB").save(output_path, "JPEG", quality=95)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
