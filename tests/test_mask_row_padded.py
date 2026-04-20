"""Маска области: построчное выравнивание и совместимость с payload."""

from __future__ import annotations

import math

from PIL import Image

from main import (
    COLOR_YELLOW,
    OP_FILL_RECT_MASK,
    RectMaskPacket,
    bitmask_size,
    _legacy_bitmask_size_continuous_unused,
    _legacy_pack_mask_from_image_continuous_unused,
)


def test_bitmask_size_row_padded_formula() -> None:
    assert bitmask_size(8, 1) == 1
    assert bitmask_size(9, 1) == 2
    assert bitmask_size(10, 2) == math.ceil(10 / 8) * 2


def test_legacy_continuous_differs_from_row_padded_for_nonaligned_width() -> None:
    w, h = 10, 2
    assert _legacy_bitmask_size_continuous_unused(w, h) != bitmask_size(w, h)


def test_rect_mask_roundtrip_single_pixel() -> None:
    w, h = 5, 3
    img = Image.new("L", (w, h), 0)
    img.putpixel((3, 1), 255)
    pkt = RectMaskPacket.from_image(0, 0, img, color_non_black=COLOR_YELLOW, op_code=OP_FILL_RECT_MASK)
    assert len(pkt.mask) == bitmask_size(w, h)
    raw = pkt.to_payload()
    back = RectMaskPacket.from_payload(raw)
    out = back.to_image()
    assert out.getpixel((3, 1)) != (0, 0, 0)
    assert out.getpixel((0, 0)) == (0, 0, 0)


def test_legacy_pack_function_is_deterministic_unused() -> None:
    img = Image.new("L", (4, 2), 0)
    img.putpixel((0, 0), 255)
    legacy = _legacy_pack_mask_from_image_continuous_unused(img)
    assert len(legacy) == _legacy_bitmask_size_continuous_unused(4, 2)
