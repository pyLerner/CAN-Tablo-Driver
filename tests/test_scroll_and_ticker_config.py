"""Проверки opcode 0x0002 и загрузки нескольких ticker-board."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from main import (  # noqa: E402
    OP_FILL_RECT_MASK,
    OP_FILL_RECT_MASK_SCROLL,
    RectMaskPacket,
    RouteAndTwoLinesTablo,
    read_u16le,
)
from led_config import load_multi_led_config  # noqa: E402


class _CaptureTransport:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def send(self, payload: bytes) -> None:
        self.payloads.append(payload)


class _FakeRenderer:
    """Без TTF: фиксированные ширины для ветвления static/scroll."""

    def measure_text_width(
        self,
        text: str,
        region_height: int,
        pad: int,
        horizontal_scale: float = 1.0,
    ) -> int:
        if text == "wide":
            return 500
        return 10

    def render(self, text: str, size: tuple[int, int], pad: int, horizontal_scale: float = 1.0):
        from PIL import Image

        return Image.new("L", size, 0)

    def render_left_aligned(
        self,
        text: str,
        region_height: int,
        pad: int,
        horizontal_scale: float = 1.0,
    ):
        from PIL import Image

        return Image.new("L", (200, region_height), 0)


def test_rect_mask_packet_accepts_scroll_opcode() -> None:
    from PIL import Image

    im = Image.new("L", (40, 20), 0)
    p = RectMaskPacket.from_image(1, 2, im, op_code=OP_FILL_RECT_MASK_SCROLL)
    p.validate()
    assert p.op_code == OP_FILL_RECT_MASK_SCROLL


def test_render_region_static_vs_scroll() -> None:
    cap = _CaptureTransport()
    r = _FakeRenderer()
    tablo = RouteAndTwoLinesTablo(
        route_width=80,
        route_text_scale_x=1.0,
        width=300,
        height=64,
        pad_left=0,
        pad_right=0,
        pad_top=2,
        pad_bottom=2,
        renderer=r,
        transport=cap,
        color_non_black=3,
    )
    tablo.render_region("short", 0, 0, 100, 30)
    assert read_u16le(cap.payloads[0], 0) == OP_FILL_RECT_MASK

    tablo.render_region("wide", 80, 0, 100, 30)
    assert read_u16le(cap.payloads[1], 0) == OP_FILL_RECT_MASK_SCROLL


def test_load_two_ticker_boards() -> None:
    toml = b"""
[can]
channel = "can0"
bitrate = 500000

[iso-tp]
rx_flowcontrol_timeout = 5000
rx_consecutive_frame_timeout = 5000
stmin = 10
blocksize = 8

[logs]
dir = "./logs"
file = "tablo.log"
count = 5
max_size = 1048576

[TextIn]
path = "./text-in.json"
font = "./DejaVuSans.ttf"

[[ticker-board]]
sender_tx_id = 0x18EF5001
sender_rx_id = 0x18EF5101
width = 256
height = 32

[[ticker-board]]
sender_tx_id = 0x18EF6001
sender_rx_id = 0x18EF6101
width = 128
height = 32
"""
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        f.write(toml)
        path = Path(f.name)
    try:
        cfg = load_multi_led_config(path)
        assert len(cfg.tickers) == 2
        assert cfg.tickers[0].sender_tx_id == 0x18EF5001
        assert cfg.tickers[1].sender_tx_id == 0x18EF6001
        assert cfg.ticker is cfg.tickers[0]
    finally:
        path.unlink(missing_ok=True)
