"""TTF font catalog for fnt-demo (Advanced Dot Digital-7)."""

from __future__ import annotations

from pathlib import Path

from .catalog import FNT_INDEX_TO_HEIGHT, VALID_FNT_INDEXES

_TOOLS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TTF_RELATIVE = Path("advanced-dot-digital-7-font") / "AdvancedDotDigital7-OpXA.ttf"


def default_ttf_path() -> Path:
    """Path to the bundled Advanced Dot Digital-7 TTF."""
    path = _TOOLS_DIR / DEFAULT_TTF_RELATIVE
    if not path.is_file():
        raise FileNotFoundError(f"TTF font not found: {path}")
    return path


def pixel_size_for_index(fnt_index: int) -> int:
    """Map --fnt-index to target pixel height (matches Compact .fnt sizes)."""
    if fnt_index not in FNT_INDEX_TO_HEIGHT:
        supported = ", ".join(str(i) for i in VALID_FNT_INDEXES)
        raise ValueError(f"Unsupported --fnt-index {fnt_index}; expected one of: {supported}")
    return FNT_INDEX_TO_HEIGHT[fnt_index]
