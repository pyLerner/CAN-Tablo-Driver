"""Compact FONT (.fnt) parser and rasterizer."""

from .catalog import FNT_INDEX_TO_FILE, VALID_FNT_INDEXES, font_path_for_index
from .parser import CompactFont, GlyphEntry, load_fnt
from .raster import decode_glyph, render_text
from .ttf_catalog import default_ttf_path, pixel_size_for_index
from .ttf_render import render_text_ttf

__all__ = [
    "CompactFont",
    "FNT_INDEX_TO_FILE",
    "GlyphEntry",
    "VALID_FNT_INDEXES",
    "decode_glyph",
    "default_ttf_path",
    "font_path_for_index",
    "load_fnt",
    "pixel_size_for_index",
    "render_text",
    "render_text_ttf",
]
