"""
Сборка табло и отправка маршрута/тикера по MultiLedConfig.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from main import (
    AbstractTablo,
    RearRouteOnlyTablo,
    RouteAndOneLineTablo,
    RouteAndTwoLinesTablo,
    TextRenderer,
    TickerBoardTablo,
)
from multi_transport import BoundMultiIsoTp, MultiIsoTpTransport

from led_config import (
    MultiLedConfig,
    RearDisplayConfig,
    RouteLikeDisplayConfig,
    TickerBoardConfig,
)

LOGGER = logging.getLogger("can-tablo")


def route_json_internal(first: str, second: str, third: str) -> str:
    return json.dumps(
        {"firstString": first, "secondString": second, "thirdString": third},
        ensure_ascii=False,
    )


def ticker_json_internal(first: str, second: str) -> str:
    return json.dumps(
        {"firstString": first, "secondString": second},
        ensure_ascii=False,
    )


def _make_route_like_tablo(
    r: RouteLikeDisplayConfig,
    renderer: TextRenderer,
    transport: BoundMultiIsoTp,
    color: int,
) -> AbstractTablo:
    common: dict = {
        "width": r.width,
        "height": r.height,
        "pad_left": r.pad_left,
        "pad_right": r.pad_right,
        "pad_top": r.pad_top,
        "pad_bottom": r.pad_bottom,
        "renderer": renderer,
        "transport": transport,
        "color_non_black": color,
    }
    if r.right_lines == 1:
        return RouteAndOneLineTablo(
            r.route_width,
            r.route_text_scale_x,
            **common,
        )
    return RouteAndTwoLinesTablo(
        r.route_width,
        r.route_text_scale_x,
        **common,
    )


def _rear_tablo(
    r: RearDisplayConfig,
    renderer: TextRenderer,
    transport: BoundMultiIsoTp,
    color: int,
) -> RearRouteOnlyTablo:
    return RearRouteOnlyTablo(
        r.route_text_scale_x,
        width=r.width,
        height=r.height,
        pad_left=r.pad_left,
        pad_right=r.pad_right,
        pad_top=r.pad_top,
        pad_bottom=r.pad_bottom,
        renderer=renderer,
        transport=transport,
        color_non_black=color,
    )


def _ticker_tablo(
    t: TickerBoardConfig,
    renderer: TextRenderer,
    transport: BoundMultiIsoTp,
    color: int,
) -> TickerBoardTablo:
    return TickerBoardTablo(
        t.ticker_lines,
        width=t.width,
        height=t.height,
        pad_left=t.pad_left,
        pad_right=t.pad_right,
        pad_top=t.pad_top,
        pad_bottom=t.pad_bottom,
        renderer=renderer,
        transport=transport,
        color_non_black=color,
    )


def collect_iso_tp_pairs(cfg: MultiLedConfig) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for sec in (cfg.front, cfg.side_front, cfg.side_rear, cfg.rear, cfg.ticker):
        if sec is None:
            continue
        p = (sec.sender_tx_id, sec.sender_rx_id)
        if p not in pairs:
            pairs.append(p)
    return pairs


def send_route_to_all_displays(cfg: MultiLedConfig, json_route: str) -> None:
    """Отправляет маршрут на переднее, боковые и заднее табло (если заданы в конфиге)."""
    renderer = TextRenderer(str(cfg.font_path))
    pairs = collect_iso_tp_pairs(cfg)
    if not pairs:
        LOGGER.warning("Нет пар CAN ID для отправки маршрута")
        return

    with MultiIsoTpTransport(
        channel=cfg.can_channel,
        bitrate=cfg.can_bitrate,
        id_pairs=pairs,
        iso_tp_params=cfg.iso_tp_params,
    ) as multi:
        color = cfg.display_color_code
        if cfg.front is not None:
            t = BoundMultiIsoTp(multi, cfg.front.sender_tx_id, cfg.front.sender_rx_id)
            tablo = _make_route_like_tablo(cfg.front, renderer, t, color)
            LOGGER.info("Маршрут -> front-display")
            tablo.send_to_tablo(json_route)
        if cfg.side_front is not None:
            t = BoundMultiIsoTp(multi, cfg.side_front.sender_tx_id, cfg.side_front.sender_rx_id)
            tablo = _make_route_like_tablo(cfg.side_front, renderer, t, color)
            LOGGER.info("Маршрут -> side-front-display")
            tablo.send_to_tablo(json_route)
        if cfg.side_rear is not None:
            t = BoundMultiIsoTp(multi, cfg.side_rear.sender_tx_id, cfg.side_rear.sender_rx_id)
            tablo = _make_route_like_tablo(cfg.side_rear, renderer, t, color)
            LOGGER.info("Маршрут -> side-rear-display")
            tablo.send_to_tablo(json_route)
        if cfg.rear is not None:
            t = BoundMultiIsoTp(multi, cfg.rear.sender_tx_id, cfg.rear.sender_rx_id)
            tablo = _rear_tablo(cfg.rear, renderer, t, color)
            LOGGER.info("Маршрут -> rear-display")
            tablo.send_to_tablo(json_route)


def send_ticker_to_board(cfg: MultiLedConfig, json_ticker: str) -> None:
    if cfg.ticker is None:
        LOGGER.warning("Секция ticker-board не задана")
        return
    renderer = TextRenderer(str(cfg.font_path))
    pairs = [(cfg.ticker.sender_tx_id, cfg.ticker.sender_rx_id)]
    with MultiIsoTpTransport(
        channel=cfg.can_channel,
        bitrate=cfg.can_bitrate,
        id_pairs=pairs,
        iso_tp_params=cfg.iso_tp_params,
    ) as multi:
        t = BoundMultiIsoTp(multi, cfg.ticker.sender_tx_id, cfg.ticker.sender_rx_id)
        tablo = _ticker_tablo(cfg.ticker, renderer, t, cfg.display_color_code)
        LOGGER.info("Тикер -> ticker-board")
        tablo.send_to_tablo(json_ticker)


def run_sender_multi(cfg: MultiLedConfig, load_text: Callable[[], str]) -> None:
    """CLI send: текст из load_text() на все маршрутные табло."""
    json_route = load_text()
    send_route_to_all_displays(cfg, json_route)
