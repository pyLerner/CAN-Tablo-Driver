"""
Конфигурация одного LED-табло: [display] + [display.N], color-map, шрифты, TOML merge.
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

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

RGB_BLACK = (0, 0, 0)
RGB_YELLOW = (255, 255, 0)
RGB_RED = (255, 0, 0)
RGB_GREEN = (0, 255, 0)
RGB_BLUE = (0, 0, 255)
RGB_CYAN = (0, 255, 255)
RGB_MAGENTA = (255, 0, 255)
RGB_WHITE = (255, 255, 255)



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


def default_color_map() -> dict[str, tuple[int, int, int]]:
    """Слоты 0 и 2 — чёрный и жёлтый на шине; остальные — для примера."""
    return {
        "0": RGB_BLACK,
        "1": (255, 255, 255),
        "2": RGB_YELLOW,
        "3": (255, 0, 0),   # RED
        "4": (0, 255, 0),   # GREEN
        "5": (0, 0, 255),   # BLUE
        "6": (0, 255, 255), # CYAN
        "7": (255, 0, 255), # MAGENTA
        "8": (128, 128, 128), # GRAY
        "9": (200, 200, 200), # LIGHT GRAY
        "10": (100, 100, 255), # LIGHT BLUE
        "11": (255, 200, 0), # ORANGE
        "12": (0, 128, 0), # LIGHT GREEN
        "13": (128, 0, 0), # DARK RED
        "14": (64, 64, 64), # DARK GRAY
        "15": (220, 220, 220), # LIGHT GRAY
    }


def rgb_tuple_matches(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return a[0] == b[0] and a[1] == b[1] and a[2] == b[2]


def rgb_index_to_wire_byte(
    palette_index: int,
    color_map: dict[str, tuple[int, int, int]],
    role: Literal["fg", "bg"],
) -> int:
    key = str(palette_index)
    rgb = color_map.get(key)
    if rgb is None:
        return COLOR_YELLOW if role == "fg" else COLOR_BLACK
    if rgb_tuple_matches(rgb, RGB_BLACK):
        return COLOR_BLACK
    if rgb_tuple_matches(rgb, RGB_YELLOW):
        return COLOR_YELLOW
    if rgb_tuple_matches(rgb, RGB_RED):
        return COLOR_RED
    if rgb_tuple_matches(rgb, RGB_GREEN):
        return COLOR_GREEN
    if rgb_tuple_matches(rgb, RGB_BLUE):
        return COLOR_BLUE
    return COLOR_YELLOW if role == "fg" else COLOR_BLACK


@dataclass(slots=True)
class ZoneArea:
    x: int
    y: int
    w: int
    h: int


@dataclass(slots=True)
class ZonePadding:
    t: int
    r: int
    b: int
    l: int


@dataclass(slots=True)
class ZoneConfig:
    bg: int
    fg: int
    font: int
    area: ZoneArea
    padding: ZonePadding
    text_scale_x: float = 1.0


def _display_id_from_section(sec: dict[str, Any]) -> str:
    if "display-id" in sec:
        return str(sec["display-id"])
    if "display_id" in sec:
        return str(sec["display_id"])
    raise ValueError("В секции [display] обязателен ключ display-id")


def _parse_area(raw: dict[str, Any]) -> ZoneArea:
    return ZoneArea(
        x=int(raw["x"]),
        y=int(raw["y"]),
        w=int(raw["w"]),
        h=int(raw["h"]),
    )


def _parse_padding(raw: dict[str, Any]) -> ZonePadding:
    return ZonePadding(
        t=int(raw["t"]),
        r=int(raw["r"]),
        b=int(raw["b"]),
        l=int(raw["l"]),
    )


def _parse_zone_raw(raw: dict[str, Any]) -> ZoneConfig:
    area_raw = raw.get("area")
    pad_raw = raw.get("padding")
    if not isinstance(area_raw, dict) or not isinstance(pad_raw, dict):
        raise ValueError("Зона должна содержать таблицы area и padding")
    return ZoneConfig(
        bg=int(raw["bg"]),
        fg=int(raw["fg"]),
        font=int(raw.get("font", 1)),
        area=_parse_area(area_raw),
        padding=_parse_padding(pad_raw),
        text_scale_x=float(raw.get("text_scale_x", 1.0)),
    )


def _parse_color_map_from_display(sec: dict[str, Any]) -> dict[str, tuple[int, int, int]]:
    raw_cm = sec.get("color_map")
    if raw_cm is None:
        return default_color_map()
    if not isinstance(raw_cm, dict):
        raise ValueError("display.color_map должен быть таблицей")
    out: dict[str, tuple[int, int, int]] = {}
    for k, v in raw_cm.items():
        sk = str(k)
        if not isinstance(v, dict):
            continue
        out[sk] = (int(v["r"]), int(v["g"]), int(v["b"]))
    dm = default_color_map()
    for i in range(16):
        sk = str(i)
        if sk not in out:
            out[sk] = dm[sk]
    return out


def _is_zone_key(key: str) -> bool:
    if key in (
        "display-id",
        "display_id",
        "sender_tx_id",
        "sender_rx_id",
        "width",
        "height",
        "color_map",
        "color",
        "animate",
        "debug",
    ):
        return False
    return key.isdigit()


def _load_zones_from_display(sec: dict[str, Any]) -> dict[str, ZoneConfig]:
    zones: dict[str, ZoneConfig] = {}
    for k, v in sec.items():
        if not _is_zone_key(str(k)):
            continue
        if not isinstance(v, dict):
            continue
        sk = str(k)
        zones[sk] = _parse_zone_raw(v)
    return zones


def _default_font_1_path(text_in_font: Path) -> Path:
    bold = text_in_font.parent / "DejaVuSans-Bold.ttf"
    if bold.is_file():
        return bold
    return text_in_font


def _load_font_paths(base_dir: Path, text_in_font: Path, raw: dict[str, Any]) -> dict[int, Path]:
    paths: dict[int, Path] = {1: _default_font_1_path(text_in_font)}
    fonts_sec = raw.get("fonts")
    if isinstance(fonts_sec, dict) and "1" in fonts_sec:
        paths[1] = resolve_path(base_dir, str(fonts_sec["1"]))
    if isinstance(fonts_sec, dict):
        for k, v in fonts_sec.items():
            if k == "1":
                continue
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            paths[idx] = resolve_path(base_dir, str(v))
    return paths


@dataclass
class MultiLedConfig:
    """Полная конфигурация сервиса (одно табло)."""

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
    api_server_host: str = "0.0.0.0"
    api_server_port: int = 8000

    display_id: str = ""
    sender_tx_id: int = 0
    sender_rx_id: int = 0
    display_width: int = 192
    display_height: int = 64
    zones: dict[str, ZoneConfig] = field(default_factory=dict)
    color_map: dict[str, tuple[int, int, int]] = field(default_factory=default_color_map)
    font_paths: dict[int, Path] = field(default_factory=dict)
    animate: bool = True
    debug: bool = False


def load_multi_led_config(config_path: Path) -> MultiLedConfig:
    with config_path.open("rb") as f:
        raw: dict[str, Any] = tomllib.load(f)

    base_dir = config_path.resolve().parent
    can_cfg = raw.get("can", {})
    iso_tp_cfg = raw.get("iso-tp", {})
    logs_cfg = raw.get("logs", {})
    text_in_cfg = raw.get("TextIn", {})
    api_sec = raw.get("api-server", {})
    display_sec = raw.get("display")

    iso_tp_params = {
        "rx_flowcontrol_timeout": int(iso_tp_cfg.get("rx_flowcontrol_timeout", 5000)),
        "rx_consecutive_frame_timeout": int(iso_tp_cfg.get("rx_consecutive_frame_timeout", 5000)),
        "stmin": int(iso_tp_cfg.get("stmin", 10)),
        "blocksize": int(iso_tp_cfg.get("blocksize", 8)),
    }

    text_in_path = resolve_path(base_dir, str(text_in_cfg.get("path", "./text-in.json")))
    font_path = resolve_path(base_dir, str(text_in_cfg.get("font", "./DejaVuSans.ttf")))
    font_paths = _load_font_paths(base_dir, font_path, raw)

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
        text_in_path=text_in_path,
        font_path=font_path,
        api_server_host=str(api_sec.get("host", "0.0.0.0")),
        api_server_port=int(api_sec.get("port", 8000)),
        font_paths=font_paths,
    )

    if not isinstance(display_sec, dict):
        raise ValueError("В config.toml обязательна секция [display]")

    cfg.display_id = _display_id_from_section(display_sec)
    cfg.sender_tx_id = int(display_sec["sender_tx_id"])
    cfg.sender_rx_id = int(display_sec["sender_rx_id"])
    cfg.display_width = int(display_sec["width"])
    cfg.display_height = int(display_sec["height"])
    cfg.color_map = _parse_color_map_from_display(display_sec)
    cfg.zones = _load_zones_from_display(display_sec)
    cfg.animate = bool(display_sec.get("animate", True))
    cfg.debug = bool(display_sec.get("debug", False))

    return cfg


def _short_path(p: Path, base: Path) -> str:
    try:
        return str(p.relative_to(base))
    except ValueError:
        return str(p)


def _zone_to_dict(z: ZoneConfig) -> dict[str, Any]:
    return {
        "bg": z.bg,
        "fg": z.fg,
        "font": z.font,
        "text_scale_x": z.text_scale_x,
        "area": {"x": z.area.x, "y": z.area.y, "w": z.area.w, "h": z.area.h},
        "padding": {"t": z.padding.t, "r": z.padding.r, "b": z.padding.b, "l": z.padding.l},
    }


def _color_map_to_nested(cm: dict[str, tuple[int, int, int]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    dm = default_color_map()
    for i in range(16):
        sk = str(i)
        r, g, b = cm.get(sk, dm[sk])
        out[sk] = {"r": r, "g": g, "b": b}
    return out


def multi_led_config_to_toml_dict(cfg: MultiLedConfig) -> dict[str, Any]:
    base = cfg.config_path.parent

    display: dict[str, Any] = {
        "display-id": cfg.display_id,
        "sender_tx_id": cfg.sender_tx_id,
        "sender_rx_id": cfg.sender_rx_id,
        "width": cfg.display_width,
        "height": cfg.display_height,
        "animate": cfg.animate,
        "debug": cfg.debug,
        "color_map": _color_map_to_nested(cfg.color_map),
    }
    for zid, zone in sorted(cfg.zones.items(), key=lambda x: int(x[0])):
        display[zid] = _zone_to_dict(zone)

    fonts_out: dict[str, Any] = {}
    if 1 in cfg.font_paths:
        fonts_out["1"] = _short_path(cfg.font_paths[1], base)

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
        "display": display,
        "api-server": {
            "host": cfg.api_server_host,
            "port": cfg.api_server_port,
        },
    }
    if fonts_out:
        out["fonts"] = fonts_out
    return out


def save_multi_led_config(cfg: MultiLedConfig) -> None:
    data = multi_led_config_to_toml_dict(cfg)
    cfg.config_path.write_text(tomli_w.dumps(data), encoding="utf-8")


def write_merged_config_toml(config_path: Path, merged: dict[str, Any]) -> None:
    config_path.write_text(tomli_w.dumps(merged), encoding="utf-8")


def merge_config_file_with_updates(
    config_path: Path,
    updates: dict[str, Any],
) -> dict[str, Any]:
    with config_path.open("rb") as f:
        current = tomllib.load(f)
    return deep_merge(current, updates)
