"""Parser for the proprietary Compact FONT (.fnt) bitmap font format."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

FONT_MAGIC = b"FONT"
HEADER_SIZE = 0x16
GLYPH_TABLE_OFFSET = HEADER_SIZE


@dataclass(slots=True)
class GlyphEntry:
    codepoint: int
    offset: int
    blob: bytes


@dataclass(slots=True)
class CompactFont:
    path: Path
    version: int
    font_id: int
    height: int
    table_offset: int
    bitmap_offset: int
    glyphs: dict[int, GlyphEntry]

    def has_codepoint(self, codepoint: int) -> bool:
        return codepoint in self.glyphs

    def glyph_blob(self, codepoint: int) -> bytes | None:
        entry = self.glyphs.get(codepoint)
        return entry.blob if entry else None

    def glyph_width(self, codepoint: int) -> int:
        from .raster import decode_glyph

        blob = self.glyph_blob(codepoint)
        if blob is None:
            return 0
        _, width = decode_glyph(blob, self.height, codepoint=codepoint)
        return width


def _parse_glyph_table(data: bytes, table_offset: int) -> tuple[list[tuple[int, int]], int]:
    max_entries = (len(data) - table_offset) // 4

    for entry_count in range(1, max_entries):
        terminator_offset = table_offset + entry_count * 4
        if terminator_offset + 4 > len(data):
            break
        terminator_cp, _ = struct.unpack_from("<HH", data, terminator_offset)
        if terminator_cp != 0:
            continue
        pool_size = len(data) - terminator_offset - 4
        entries: list[tuple[int, int]] = []
        valid = True
        for index in range(entry_count):
            codepoint, blob_offset = struct.unpack_from(
                "<HH", data, table_offset + index * 4
            )
            if codepoint == 0 or blob_offset >= pool_size:
                valid = False
                break
            entries.append((codepoint, blob_offset))
        if valid:
            return entries, terminator_offset + 4

    for entry_count in range(max_entries, 0, -1):
        pool_size = len(data) - table_offset - entry_count * 4
        if pool_size <= 0:
            continue
        entries = []
        valid = True
        for index in range(entry_count):
            codepoint, blob_offset = struct.unpack_from(
                "<HH", data, table_offset + index * 4
            )
            if codepoint == 0 or blob_offset >= pool_size:
                valid = False
                break
            entries.append((codepoint, blob_offset))
        if valid:
            return entries, table_offset + entry_count * 4

    raise ValueError("unable to locate a valid glyph index table")


def _build_glyph_blobs(bitmap_pool: bytes, indexed: list[tuple[int, int]]) -> dict[int, GlyphEntry]:
    unique_offsets = sorted({blob_offset for _, blob_offset in indexed})
    end_by_offset = {
        unique_offsets[i]: unique_offsets[i + 1]
        for i in range(len(unique_offsets) - 1)
    }
    pool_end = len(bitmap_pool)

    glyphs: dict[int, GlyphEntry] = {}
    for codepoint, blob_offset in indexed:
        end = end_by_offset.get(blob_offset, pool_end)
        glyphs[codepoint] = GlyphEntry(
            codepoint=codepoint,
            offset=blob_offset,
            blob=bitmap_pool[blob_offset:end],
        )
    return glyphs


def load_fnt(path: str | Path, *, expected_font_id: int | None = None) -> CompactFont:
    """Load a Compact .fnt file from disk."""
    font_path = Path(path)
    data = font_path.read_bytes()

    if len(data) < HEADER_SIZE + 4:
        raise ValueError(f"{font_path}: file too small for Compact FONT format")
    if data[:4] != FONT_MAGIC:
        raise ValueError(f"{font_path}: invalid magic {data[:4]!r}, expected {FONT_MAGIC!r}")

    version = data[4]
    if version != 1:
        raise ValueError(f"{font_path}: unsupported FONT version {version}")

    font_id = data[5]
    height = struct.unpack_from("<H", data, 6)[0]
    if expected_font_id is not None and font_id != expected_font_id:
        raise ValueError(
            f"{font_path}: font id {font_id} does not match expected index {expected_font_id}"
        )

    indexed, table_end = _parse_glyph_table(data, GLYPH_TABLE_OFFSET)
    if not indexed:
        raise ValueError(f"{font_path}: empty glyph table")

    if table_end > len(data):
        raise ValueError(f"{font_path}: glyph table overruns file")

    bitmap_pool = data[table_end:]
    glyphs = _build_glyph_blobs(bitmap_pool, indexed)

    return CompactFont(
        path=font_path,
        version=version,
        font_id=font_id,
        height=height,
        table_offset=GLYPH_TABLE_OFFSET,
        bitmap_offset=table_end,
        glyphs=glyphs,
    )
