"""
Сборка табло по зонам и отправка на одно табло (MultiLedConfig).
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from main import TextRenderer, ZonedDisplayTablo
from multi_transport import BoundMultiIsoTp, MultiIsoTpTransport

from led_config import MultiLedConfig

LOGGER = logging.getLogger("can-tablo")


def values_json(values: dict[str, str]) -> str:
    return json.dumps({"values": values}, ensure_ascii=False)


def send_display_values(cfg: MultiLedConfig, values: dict[str, str]) -> None:
    """Отправляет строки зон на единственное табло из [display]."""
    if not cfg.zones:
        LOGGER.warning("Нет зон в конфиге — нечего отправлять")
        return
    renderer = TextRenderer(str(cfg.font_path))
    pair = (cfg.sender_tx_id, cfg.sender_rx_id)
    payload = values_json(values)

    with MultiIsoTpTransport(
        channel=cfg.can_channel,
        bitrate=cfg.can_bitrate,
        id_pairs=[pair],
        iso_tp_params=cfg.iso_tp_params,
    ) as multi:
        transport = BoundMultiIsoTp(multi, cfg.sender_tx_id, cfg.sender_rx_id)
        tablo = ZonedDisplayTablo(cfg, renderer, transport)
        LOGGER.info(
            "Отправка на табло display-id=%s tx=%#x rx=%#x",
            cfg.display_id,
            cfg.sender_tx_id,
            cfg.sender_rx_id,
        )
        tablo.send_to_tablo(payload)


def run_sender_multi(cfg: MultiLedConfig, load_text: Callable[[], str]) -> None:
    """CLI send: JSON с полем values (или объект зона→строка) из load_text()."""
    raw = load_text()
    data = json.loads(raw)
    v = data.get("values", data)
    if not isinstance(v, dict):
        v = {}
    values = {str(k): str(val) for k, val in v.items()}
    send_display_values(cfg, values)
