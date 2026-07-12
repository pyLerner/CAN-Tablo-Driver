"""Catalog of Compact .fnt files shipped with the project."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FONTS_DIR = REPO_ROOT / "#60 Compact"

FNT_INDEX_TO_FILE: dict[int, str] = {
    62: "#62 - Compact 08x (Georgian).fnt",
    63: "#63 - Compact 10x.fnt",
    65: "#65 - Compact 16x.fnt",
    66: "#66 - Compact 20x.fnt",
    67: "#67 - Compact 24x.fnt",
    68: "#68 - Compact 32x.fnt",
    69: "#69 - Compact 40x.fnt",
}

FNT_INDEX_TO_HEIGHT: dict[int, int] = {
    62: 8,
    63: 10,
    65: 16,
    66: 20,
    67: 24,
    68: 32,
    69: 40,
}

VALID_FNT_INDEXES = tuple(sorted(FNT_INDEX_TO_FILE))


def font_path_for_index(index: int) -> Path:
    """Resolve catalog index to an on-disk .fnt path."""
    if index not in FNT_INDEX_TO_FILE:
        supported = ", ".join(str(i) for i in VALID_FNT_INDEXES)
        raise ValueError(f"Unsupported --fnt-index {index}; expected one of: {supported}")
    path = FONTS_DIR / FNT_INDEX_TO_FILE[index]
    if not path.is_file():
        raise FileNotFoundError(f"Font file not found: {path}")
    return path
