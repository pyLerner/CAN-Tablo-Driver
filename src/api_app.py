"""
REST API (FastAPI): конфигурация зон и обновление строк — контракт V2.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from led_config import (
    MultiLedConfig,
    load_multi_led_config,
    merge_config_file_with_updates,
    write_merged_config_toml,
)
from led_service import send_display_values

DEFAULT_CONFIG_PATH = _SRC / "config.toml"


class ColorRgb(BaseModel):
    model_config = ConfigDict(extra="forbid")

    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


class AreaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int
    y: int
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class PaddingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: int = Field(ge=0)
    r: int = Field(ge=0)
    b: int = Field(ge=0)
    l: int = Field(ge=0)


class ZoneBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bg: int = Field(ge=0, le=15)
    fg: int = Field(ge=0, le=15)
    font: int = Field(default=1, ge=1)
    area: AreaBody
    padding: PaddingBody
    text_scale_x: Optional[float] = Field(default=None, ge=0.01)


class ConfigSetBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    color_map: Optional[dict[str, ColorRgb]] = Field(default=None, alias="color-map")
    zones: Optional[dict[str, ZoneBody]] = None
    channel: Optional[str] = None
    bitrate: Optional[int] = None


class ValuesUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    values: dict[str, str]

    @field_validator("values", mode="before")
    @classmethod
    def _coerce_keys(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        return {str(k): str(val) for k, val in v.items()}


class PingResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, ser_json_by_alias=True)

    running: str = "OK"
    timestamp_utc: str = Field(serialization_alias="timestamp-utc")
    display_id: str = Field(serialization_alias="display-id")


def _zone_body_to_toml(z: ZoneBody) -> dict[str, Any]:
    d: dict[str, Any] = {
        "bg": z.bg,
        "fg": z.fg,
        "font": z.font,
        "area": {"x": z.area.x, "y": z.area.y, "w": z.area.w, "h": z.area.h},
        "padding": {
            "t": z.padding.t,
            "r": z.padding.r,
            "b": z.padding.b,
            "l": z.padding.l,
        },
    }
    if z.text_scale_x is not None:
        d["text_scale_x"] = z.text_scale_x
    return d


def _config_set_body_to_toml_updates(body: ConfigSetBody) -> dict[str, Any]:
    upd: dict[str, Any] = {}
    if body.channel is not None or body.bitrate is not None:
        can: dict[str, Any] = {}
        if body.channel is not None:
            can["channel"] = body.channel
        if body.bitrate is not None:
            can["bitrate"] = body.bitrate
        upd["can"] = can

    display: dict[str, Any] = {}
    if body.color_map is not None:
        display["color_map"] = {
            k: {"r": c.r, "g": c.g, "b": c.b} for k, c in body.color_map.items()
        }
    if body.zones is not None:
        for zk, zv in body.zones.items():
            display[str(zk)] = _zone_body_to_toml(zv)
    if display:
        upd["display"] = display
    return upd


class AppState:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config: MultiLedConfig = load_multi_led_config(config_path)
        self.last_values: dict[str, str] = {}


def create_app(config_path: Optional[Path] = None) -> FastAPI:
    path = config_path or DEFAULT_CONFIG_PATH
    state = AppState(path)

    app = FastAPI(title="LED displays CAN service", version="2")

    @app.get("/api/ping", response_model=PingResponse, response_model_by_alias=True)
    def ping() -> PingResponse:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
        return PingResponse(
            running="OK",
            timestamp_utc=ts,
            display_id=state.config.display_id,
        )

    @app.post("/api/leddisplays/v1/config/set")
    async def config_set(body: ConfigSetBody) -> dict[str, str]:
        updates = _config_set_body_to_toml_updates(body)
        if not updates:
            return {"status": "noop"}

        merged = merge_config_file_with_updates(state.config_path, updates)
        write_merged_config_toml(state.config_path, merged)
        state.config = load_multi_led_config(state.config_path)
        return {"status": "ok"}

    @app.put("/api/leddisplays/v1/values/update")
    async def values_update(body: ValuesUpdateBody) -> dict[str, str]:
        state.last_values = dict(body.values)

        async def _job() -> None:
            await asyncio.to_thread(send_display_values, state.config, state.last_values)

        asyncio.create_task(_job())
        return {"status": "accepted"}

    return app


app = create_app()
