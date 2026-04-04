"""Маппинг палитры color_map → байт цвета на шине (RGB → COLOR_*)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from led_config import (  # noqa: E402
    COLOR_BLACK,
    COLOR_BLUE,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_YELLOW,
    default_color_map,
    rgb_index_to_wire_byte,
)


def test_default_map_red_green_blue_wire_fg() -> None:
    cm = default_color_map()
    assert rgb_index_to_wire_byte(3, cm, "fg") == COLOR_RED
    assert rgb_index_to_wire_byte(4, cm, "fg") == COLOR_GREEN
    assert rgb_index_to_wire_byte(5, cm, "fg") == COLOR_BLUE


def test_default_map_red_green_blue_wire_bg() -> None:
    cm = default_color_map()
    assert rgb_index_to_wire_byte(3, cm, "bg") == COLOR_RED
    assert rgb_index_to_wire_byte(4, cm, "bg") == COLOR_GREEN
    assert rgb_index_to_wire_byte(5, cm, "bg") == COLOR_BLUE


def test_black_yellow_unchanged() -> None:
    cm = default_color_map()
    assert rgb_index_to_wire_byte(0, cm, "fg") == COLOR_BLACK
    assert rgb_index_to_wire_byte(0, cm, "bg") == COLOR_BLACK
    assert rgb_index_to_wire_byte(2, cm, "fg") == COLOR_YELLOW
    assert rgb_index_to_wire_byte(2, cm, "bg") == COLOR_YELLOW


def test_unknown_rgb_fallback() -> None:
    cm = {"9": (200, 200, 200)}
    assert rgb_index_to_wire_byte(9, cm, "fg") == COLOR_YELLOW
    assert rgb_index_to_wire_byte(9, cm, "bg") == COLOR_BLACK


def test_missing_index_fallback() -> None:
    cm: dict[str, tuple[int, int, int]] = {}
    assert rgb_index_to_wire_byte(1, cm, "fg") == COLOR_YELLOW
    assert rgb_index_to_wire_byte(1, cm, "bg") == COLOR_BLACK
