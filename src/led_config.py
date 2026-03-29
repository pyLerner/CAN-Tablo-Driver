"""
Мультисекционная конфигурация LED-табло: загрузка/сохранение TOML, слияние, цвет.
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import tomli_w

# Согласовано с main.COLOR_*
COLOR_BLACK = 0x00
COLOR_RED = 0x01
COLOR_GREEN = 0x02
COLOR_BLUE = 0x04
COLOR_YELLOW = 0x03
COLOR_CYAN = 0x06
COLOR_MAGENTA = 0x05
COLOR_WHITE = 0x07

COLOR_NAME_TO_CODE: dict[str, int] = {
    "BLACK": COLOR_BLACK,
    "RED": COLOR_RED,
    "GREEN": COLOR_GREEN,
    "BLUE": COLOR_BLUE,
    "YELLOW": COLOR_YELLOW,
    "CYAN": COLOR_CYAN,
    "MAGENTA": COLOR_MAGENTA,
    "WHITE": COLOR_WHITE,
}


def _code_to_color_name(code: int) -> str:
    for name, c in COLOR_NAME_TO_CODE.items():
        if c == code:
            return name
    return "YELLOW"


def parse_color_name(name: str) -> int:
    key = name.strip().upper()
    if key not in COLOR_NAME_TO_CODE:
        raise ValueError(f"Неизвестный цвет: {name!r}, допустимо: {sorted(COLOR_NAME_TO_CODE)}")
    return COLOR_NAME_TO_CODE[key]


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in update.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@dataclass(slots=True)
class RouteLikeDisplayConfig:
    """Переднее/боковое: маршрут + 1–2 строки справа."""

    sender_tx_id: int
    sender_rx_id: int
    route_width: int
    route_text_scale_x: float
    width: int
    height: int
    pad_left: int
    pad_right: int
    pad_top: int
    pad_bottom: int
    right_lines: int  # 1 или 2


@dataclass(slots=True)
class RearDisplayConfig:
    """Задний указатель: только номер маршрута на всё поле."""

    sender_tx_id: int
    sender_rx_id: int
    route_text_scale_x: float
    width: int
    height: int
    pad_left: int
    pad_right: int
    pad_top: int
    pad_bottom: int


@dataclass(slots=True)
class TickerBoardConfig:
    """Внутрисалонная строка: 1 или 2 строки на всю ширину."""

    sender_tx_id: int
    sender_rx_id: int
    width: int
    height: int
    pad_left: int
    pad_right: int
    pad_top: int
    pad_bottom: int
    ticker_lines: int  # 1 или 2


@dataclass
class MultiLedConfig:
    """Полная конфигурация сервиса."""

    config_path: Path
    can_channel: str
    can_bitrate: int
    iso_tp_params: dict[str, int]
    use_stack_sleep_time: bool
    loop_sleep_sec: float
    logs_dir: Path
    log_filename: str
    log_backup_count: int
    log_max_bytes: int
    text_in_path: Path
    font_path: Path
    display_color_code: int
    front: Optional[RouteLikeDisplayConfig] = None
    side_front: Optional[RouteLikeDisplayConfig] = None
    side_rear: Optional[RouteLikeDisplayConfig] = None
    rear: Optional[RearDisplayConfig] = None
    ticker: Optional[TickerBoardConfig] = None

    # Legacy single-tablo (для CLI send без новых секций)
    legacy_sender_tx_id: Optional[int] = None
    legacy_sender_rx_id: Optional[int] = None
    legacy_route_width: int = 80
    legacy_route_text_scale_x: float = 1.0
    legacy_tablo_width: int = 192
    legacy_tablo_height: int = 64
    legacy_pad_left: int = 0
    legacy_pad_right: int = 0
    legacy_pad_top: int = 2
    legacy_pad_bottom: int = 2

    api_server_host: str = "0.0.0.0"
    api_server_port: int = 8000


def _section_route_from_raw(sec: dict[str, Any]) -> RouteLikeDisplayConfig:
    return RouteLikeDisplayConfig(
        sender_tx_id=int(sec["sender_tx_id"]),
        sender_rx_id=int(sec["sender_rx_id"]),
        route_width=int(sec.get("route_width", 80)),
        route_text_scale_x=float(sec.get("route_text_scale_x", 1.0)),
        width=int(sec["width"]),
        height=int(sec["height"]),
        pad_left=int(sec.get("pad_left", 0)),
        pad_right=int(sec.get("pad_right", 0)),
        pad_top=int(sec.get("pad_top", 2)),
        pad_bottom=int(sec.get("pad_bottom", 2)),
        right_lines=int(sec.get("right_lines", 2)),
    )


def _section_rear_from_raw(sec: dict[str, Any]) -> RearDisplayConfig:
    return RearDisplayConfig(
        sender_tx_id=int(sec["sender_tx_id"]),
        sender_rx_id=int(sec["sender_rx_id"]),
        route_text_scale_x=float(sec.get("route_text_scale_x", 1.0)),
        width=int(sec["width"]),
        height=int(sec["height"]),
        pad_left=int(sec.get("pad_left", 0)),
        pad_right=int(sec.get("pad_right", 0)),
        pad_top=int(sec.get("pad_top", 2)),
        pad_bottom=int(sec.get("pad_bottom", 2)),
    )


def _section_ticker_from_raw(sec: dict[str, Any]) -> TickerBoardConfig:
    return TickerBoardConfig(
        sender_tx_id=int(sec["sender_tx_id"]),
        sender_rx_id=int(sec["sender_rx_id"]),
        width=int(sec["width"]),
        height=int(sec["height"]),
        pad_left=int(sec.get("pad_left", 0)),
        pad_right=int(sec.get("pad_right", 0)),
        pad_top=int(sec.get("pad_top", 2)),
        pad_bottom=int(sec.get("pad_bottom", 2)),
        ticker_lines=int(sec.get("ticker_lines", 2)),
    )


def load_multi_led_config(config_path: Path) -> MultiLedConfig:
    with config_path.open("rb") as f:
        raw: dict[str, Any] = tomllib.load(f)

    base_dir = config_path.resolve().parent
    can_cfg = raw.get("can", {})
    iso_tp_cfg = raw.get("iso-tp", {})
    logs_cfg = raw.get("logs", {})
    text_in_cfg = raw.get("TextIn", {})
    legacy_tablo = raw.get("tabloRouteTwoStrings", {})
    color_sec = raw.get("display", {})
    api_sec = raw.get("api-server", {})

    iso_tp_params = {
        "rx_flowcontrol_timeout": int(iso_tp_cfg.get("rx_flowcontrol_timeout", 5000)),
        "rx_consecutive_frame_timeout": int(iso_tp_cfg.get("rx_consecutive_frame_timeout", 5000)),
        "stmin": int(iso_tp_cfg.get("stmin", 10)),
        "blocksize": int(iso_tp_cfg.get("blocksize", 8)),
    }

    display_color_code = COLOR_YELLOW
    if "color" in color_sec:
        display_color_code = parse_color_name(str(color_sec["color"]))

    cfg = MultiLedConfig(
        config_path=config_path,
        can_channel=str(can_cfg.get("channel", "can0")),
        can_bitrate=int(can_cfg.get("bitrate", 500_000)),
        iso_tp_params=iso_tp_params,
        use_stack_sleep_time=bool(iso_tp_cfg.get("use_stack_sleep_time", True)),
        loop_sleep_sec=float(iso_tp_cfg.get("loop_sleep_sec", 0.0001)),
        logs_dir=resolve_path(base_dir, str(logs_cfg.get("dir", "./logs"))),
        log_filename=str(logs_cfg.get("file", "tablo.log")),
        log_backup_count=int(logs_cfg.get("count", 5)),
        log_max_bytes=int(logs_cfg.get("max_size", 1_048_576)),
        text_in_path=resolve_path(base_dir, str(text_in_cfg.get("path", "./text-in.json"))),
        font_path=resolve_path(base_dir, str(text_in_cfg.get("font", "./DejaVuSans.ttf"))),
        display_color_code=display_color_code,
        legacy_sender_tx_id=int(can_cfg["sender_tx_id"]) if "sender_tx_id" in can_cfg else None,
        legacy_sender_rx_id=int(can_cfg["sender_rx_id"]) if "sender_rx_id" in can_cfg else None,
        legacy_route_width=int(legacy_tablo.get("route_width", 80)),
        legacy_route_text_scale_x=float(legacy_tablo.get("route_text_scale_x", 1.0)),
        legacy_tablo_width=int(legacy_tablo.get("width", 192)),
        legacy_tablo_height=int(legacy_tablo.get("height", 64)),
        legacy_pad_left=int(legacy_tablo.get("pad_left", 0)),
        legacy_pad_right=int(legacy_tablo.get("pad_right", 0)),
        legacy_pad_top=int(legacy_tablo.get("pad_top", 2)),
        legacy_pad_bottom=int(legacy_tablo.get("pad_bottom", 2)),
        api_server_host=str(api_sec.get("host", "0.0.0.0")),
        api_server_port=int(api_sec.get("port", 8000)),
    )

    if "front-display" in raw:
        cfg.front = _section_route_from_raw(raw["front-display"])
    if "side-front-display" in raw:
        cfg.side_front = _section_route_from_raw(raw["side-front-display"])
    if "side-rear-display" in raw:
        cfg.side_rear = _section_route_from_raw(raw["side-rear-display"])
    if "rear-display" in raw:
        cfg.rear = _section_rear_from_raw(raw["rear-display"])
    if "ticker-board" in raw:
        cfg.ticker = _section_ticker_from_raw(raw["ticker-board"])

    if (
        cfg.front is None
        and cfg.legacy_sender_tx_id is not None
        and cfg.legacy_sender_rx_id is not None
    ):
        cfg.front = RouteLikeDisplayConfig(
            sender_tx_id=cfg.legacy_sender_tx_id,
            sender_rx_id=cfg.legacy_sender_rx_id,
            route_width=cfg.legacy_route_width,
            route_text_scale_x=cfg.legacy_route_text_scale_x,
            width=cfg.legacy_tablo_width,
            height=cfg.legacy_tablo_height,
            pad_left=cfg.legacy_pad_left,
            pad_right=cfg.legacy_pad_right,
            pad_top=cfg.legacy_pad_top,
            pad_bottom=cfg.legacy_pad_bottom,
            right_lines=2,
        )

    return cfg


def _short_path(p: Path, base: Path) -> str:
    try:
        return str(p.relative_to(base))
    except ValueError:
        return str(p)


def multi_led_config_to_toml_dict(cfg: MultiLedConfig) -> dict[str, Any]:
    """Сериализация в плоский TOML-совместимый dict."""

    base = cfg.config_path.parent

    def route_to_dict(r: RouteLikeDisplayConfig) -> dict[str, Any]:
        return {
            "sender_tx_id": r.sender_tx_id,
            "sender_rx_id": r.sender_rx_id,
            "route_width": r.route_width,
            "route_text_scale_x": r.route_text_scale_x,
            "width": r.width,
            "height": r.height,
            "pad_left": r.pad_left,
            "pad_right": r.pad_right,
            "pad_top": r.pad_top,
            "pad_bottom": r.pad_bottom,
            "right_lines": r.right_lines,
        }

    def rear_to_dict(r: RearDisplayConfig) -> dict[str, Any]:
        return {
            "sender_tx_id": r.sender_tx_id,
            "sender_rx_id": r.sender_rx_id,
            "route_text_scale_x": r.route_text_scale_x,
            "width": r.width,
            "height": r.height,
            "pad_left": r.pad_left,
            "pad_right": r.pad_right,
            "pad_top": r.pad_top,
            "pad_bottom": r.pad_bottom,
        }

    def ticker_to_dict(t: TickerBoardConfig) -> dict[str, Any]:
        return {
            "sender_tx_id": t.sender_tx_id,
            "sender_rx_id": t.sender_rx_id,
            "width": t.width,
            "height": t.height,
            "pad_left": t.pad_left,
            "pad_right": t.pad_right,
            "pad_top": t.pad_top,
            "pad_bottom": t.pad_bottom,
            "ticker_lines": t.ticker_lines,
        }

    out: dict[str, Any] = {
        "can": {
            "channel": cfg.can_channel,
            "bitrate": cfg.can_bitrate,
        },
        "iso-tp": {
            "rx_flowcontrol_timeout": cfg.iso_tp_params["rx_flowcontrol_timeout"],
            "rx_consecutive_frame_timeout": cfg.iso_tp_params["rx_consecutive_frame_timeout"],
            "stmin": cfg.iso_tp_params["stmin"],
            "blocksize": cfg.iso_tp_params["blocksize"],
            "use_stack_sleep_time": cfg.use_stack_sleep_time,
            "loop_sleep_sec": cfg.loop_sleep_sec,
        },
        "logs": {
            "dir": _short_path(cfg.logs_dir, base),
            "file": cfg.log_filename,
            "count": cfg.log_backup_count,
            "max_size": cfg.log_max_bytes,
        },
        "TextIn": {
            "path": _short_path(cfg.text_in_path, base),
            "font": _short_path(cfg.font_path, base),
        },
        "display": {
            "color": _code_to_color_name(cfg.display_color_code),
        },
        "api-server": {
            "host": cfg.api_server_host,
            "port": cfg.api_server_port,
        },
    }

    # Legacy секции для совместимости с однотабличным CLI
    if cfg.legacy_sender_tx_id is not None and cfg.legacy_sender_rx_id is not None:
        out["can"]["sender_tx_id"] = cfg.legacy_sender_tx_id
        out["can"]["sender_rx_id"] = cfg.legacy_sender_rx_id

    out["tabloRouteTwoStrings"] = {
        "route_width": cfg.legacy_route_width,
        "route_text_scale_x": cfg.legacy_route_text_scale_x,
        "width": cfg.legacy_tablo_width,
        "height": cfg.legacy_tablo_height,
        "pad_left": cfg.legacy_pad_left,
        "pad_right": cfg.legacy_pad_right,
        "pad_top": cfg.legacy_pad_top,
        "pad_bottom": cfg.legacy_pad_bottom,
    }

    if cfg.front:
        out["front-display"] = route_to_dict(cfg.front)
    if cfg.side_front:
        out["side-front-display"] = route_to_dict(cfg.side_front)
    if cfg.side_rear:
        out["side-rear-display"] = route_to_dict(cfg.side_rear)
    if cfg.rear:
        out["rear-display"] = rear_to_dict(cfg.rear)
    if cfg.ticker:
        out["ticker-board"] = ticker_to_dict(cfg.ticker)

    return out


def save_multi_led_config(cfg: MultiLedConfig) -> None:
    data = multi_led_config_to_toml_dict(cfg)
    cfg.config_path.write_text(tomli_w.dumps(data), encoding="utf-8")


def write_merged_config_toml(config_path: Path, merged: dict[str, Any]) -> None:
    """Записывает слитый TOML (после deep_merge с файлом и API)."""
    config_path.write_text(tomli_w.dumps(merged), encoding="utf-8")


def merge_config_file_with_updates(
    config_path: Path,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Загружает TOML с диска и выполняет deep_merge с updates."""
    with config_path.open("rb") as f:
        current = tomllib.load(f)
    return deep_merge(current, updates)
