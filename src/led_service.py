"""
Сборка табло по зонам и отправка на одно табло (MultiLedConfig).
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from main import TextRenderer, ZonedDisplayTablo
from multi_transport import BoundMultiIsoTp, MultiIsoTpTransport

from led_config import MultiLedConfig, load_multi_led_config

LOGGER = logging.getLogger("can-tablo")


def values_json(values: dict[str, str]) -> str:
    return json.dumps({"values": values}, ensure_ascii=False)


class DisplayTransport:
    """Долгоживущий CAN/ISO-TP транспорт для сериализованной отправки."""

    def __init__(self) -> None:
        self._multi: Optional[MultiIsoTpTransport] = None
        self._bound: Optional[BoundMultiIsoTp] = None
        self._cfg: Optional[MultiLedConfig] = None

    @property
    def is_open(self) -> bool:
        return self._multi is not None

    def open(self, cfg: MultiLedConfig) -> None:
        if self.is_open:
            self.close()
        pair = (cfg.sender_tx_id, cfg.sender_rx_id)
        self._multi = MultiIsoTpTransport(
            channel=cfg.can_channel,
            bitrate=cfg.can_bitrate,
            id_pairs=[pair],
            iso_tp_params=cfg.iso_tp_params,
        )
        self._bound = BoundMultiIsoTp(self._multi, cfg.sender_tx_id, cfg.sender_rx_id)
        self._cfg = cfg

    def close(self) -> None:
        if self._multi is not None:
            self._multi.close()
        self._multi = None
        self._bound = None
        self._cfg = None

    def send_display_values(self, cfg: MultiLedConfig, values: dict[str, str]) -> None:
        if not self.is_open or self._bound is None:
            raise RuntimeError("DisplayTransport не открыт")
        _send_display_values_with_transport(cfg, self._bound, values)

    def __enter__(self) -> "DisplayTransport":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def _send_display_values_with_transport(
    cfg: MultiLedConfig,
    transport: BoundMultiIsoTp,
    values: dict[str, str],
) -> None:
    cfg = load_multi_led_config(cfg.config_path)
    if not cfg.zones:
        LOGGER.warning("Нет зон в конфиге — нечего отправлять")
        return
    renderer = TextRenderer(str(cfg.font_path))
    payload = values_json(values)
    tablo = ZonedDisplayTablo(cfg, renderer, transport)
    LOGGER.info(
        "Отправка на табло display-id=%s tx=%#x rx=%#x",
        cfg.display_id,
        cfg.sender_tx_id,
        cfg.sender_rx_id,
    )
    tablo.send_to_tablo(payload)


def send_display_values(
    cfg: MultiLedConfig,
    values: dict[str, str],
    transport: Optional[DisplayTransport] = None,
) -> None:
    """Отправляет строки зон на единственное табло из [display]."""
    if transport is not None and transport.is_open:
        transport.send_display_values(cfg, values)
        return

    cfg = load_multi_led_config(cfg.config_path)
    if not cfg.zones:
        LOGGER.warning("Нет зон в конфиге — нечего отправлять")
        return
    pair = (cfg.sender_tx_id, cfg.sender_rx_id)
    with MultiIsoTpTransport(
        channel=cfg.can_channel,
        bitrate=cfg.can_bitrate,
        id_pairs=[pair],
        iso_tp_params=cfg.iso_tp_params,
    ) as multi:
        bound = BoundMultiIsoTp(multi, cfg.sender_tx_id, cfg.sender_rx_id)
        _send_display_values_with_transport(cfg, bound, values)


def run_sender_multi(cfg: MultiLedConfig, load_text: Callable[[], str]) -> None:
    """CLI send: JSON с полем values (или объект зона→строка) из load_text()."""
    raw = load_text()
    data = json.loads(raw)
    v = data.get("values", data)
    if not isinstance(v, dict):
        v = {}
    values = {str(k): str(val) for k, val in v.items()}
    send_display_values(cfg, values)
