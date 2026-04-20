"""Усечение текста по ширине (нужен системный TTF)."""

from __future__ import annotations

from pathlib import Path

import pytest

from main import TextRenderer


def _dejavu_path() -> Path:
    return Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


@pytest.fixture
def font_path() -> str:
    p = _dejavu_path()
    if not p.is_file():
        pytest.skip("DejaVu Sans not found (install fonts-dejavu-core)")
    return str(p)


def test_truncate_empty_and_fits(font_path: str) -> None:
    r = TextRenderer(font_path)
    assert r.truncate_text_to_width("", 24, 2, 100) == ""
    s = "Hi"
    assert r.truncate_text_to_width(s, 24, 2, 500) == s


def test_truncate_prefix_shortens(font_path: str) -> None:
    r = TextRenderer(font_path)
    long = "A" * 80
    short = r.truncate_text_to_width(long, 20, 2, 40)
    assert len(short) < len(long)
    assert r.measure_text_width(short, 20, 2) <= 40
