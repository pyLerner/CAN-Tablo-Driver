"""
REST API для настройки табло и отправки маршрута/тикера (FastAPI).
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

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from led_config import (
    MultiLedConfig,
    load_multi_led_config,
    merge_config_file_with_updates,
    parse_color_name,
    write_merged_config_toml,
)
from led_service import (
    route_json_internal,
    send_route_to_all_displays,
    send_ticker_to_board,
    ticker_json_internal,
)

DEFAULT_CONFIG_PATH = _SRC / "config.toml"


class DisplayBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_tx_id: Optional[int] = Field(default=None, alias="sender-tx-id")
    sender_rx_id: Optional[int] = Field(default=None, alias="sender-rx-id")
    route_width: Optional[int] = Field(default=None, alias="route-width")
    route_text_scale_x: Optional[float] = Field(default=None, alias="route-text-scale-x")
    width: Optional[int] = None
    height: Optional[int] = None
    pad_left: Optional[int] = Field(default=None, alias="pad-left")
    pad_right: Optional[int] = Field(default=None, alias="pad-right")
    pad_top: Optional[int] = Field(default=None, alias="pad-top")
    pad_bottom: Optional[int] = Field(default=None, alias="pad-bottom")
    right_lines: Optional[int] = Field(default=None, alias="right-lines")
    ticker_lines: Optional[int] = Field(default=None, alias="ticker-lines")


class ConfigSetBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    color: Optional[str] = None
    channel: Optional[str] = None
    bitrate: Optional[int] = None
    front_display: Optional[DisplayBlock] = Field(default=None, alias="front-display")
    side_front_display: Optional[DisplayBlock] = Field(default=None, alias="side-front-display")
    side_rear_display: Optional[DisplayBlock] = Field(default=None, alias="side-rear-display")
    rear_display: Optional[DisplayBlock] = Field(default=None, alias="rear-display")
    ticker_board: Optional[DisplayBlock] = Field(default=None, alias="ticker-board")


class RouteSetBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    first_string: str = Field(alias="first-string")
    second_string: str = Field(default="", alias="second-string")
    third_string: str = Field(default="", alias="third-string")


class RouteGetResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, ser_json_by_alias=True)

    first_string: str = Field(serialization_alias="first-string")
    second_string: str = Field(serialization_alias="second-string")
    third_string: str = Field(serialization_alias="third-string")


class TickerSetBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    first_string: str = Field(alias="first-string")
    second_string: str = Field(default="", alias="second-string")


class PingResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, ser_json_by_alias=True)

    running: str = "OK"
    timestamp_utc: str = Field(serialization_alias="timestamp-utc")


def _display_block_to_toml_section(block: DisplayBlock) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if block.sender_tx_id is not None:
        d["sender_tx_id"] = block.sender_tx_id
    if block.sender_rx_id is not None:
        d["sender_rx_id"] = block.sender_rx_id
    if block.route_width is not None:
        d["route_width"] = block.route_width
    if block.route_text_scale_x is not None:
        d["route_text_scale_x"] = block.route_text_scale_x
    if block.width is not None:
        d["width"] = block.width
    if block.height is not None:
        d["height"] = block.height
    if block.pad_left is not None:
        d["pad_left"] = block.pad_left
    if block.pad_right is not None:
        d["pad_right"] = block.pad_right
    if block.pad_top is not None:
        d["pad_top"] = block.pad_top
    if block.pad_bottom is not None:
        d["pad_bottom"] = block.pad_bottom
    if block.right_lines is not None:
        d["right_lines"] = block.right_lines
    if block.ticker_lines is not None:
        d["ticker_lines"] = block.ticker_lines
    return d


def _config_set_body_to_toml_updates(body: ConfigSetBody) -> dict[str, Any]:
    """Слияние в формат ключей TOML (как в файле)."""
    upd: dict[str, Any] = {}
    if body.color is not None:
        upd["display"] = {"color": body.color.upper()}
    if body.channel is not None or body.bitrate is not None:
        can = {}
        if body.channel is not None:
            can["channel"] = body.channel
        if body.bitrate is not None:
            can["bitrate"] = body.bitrate
        upd["can"] = can
    if body.front_display is not None:
        upd["front-display"] = _display_block_to_toml_section(body.front_display)
    if body.side_front_display is not None:
        upd["side-front-display"] = _display_block_to_toml_section(body.side_front_display)
    if body.side_rear_display is not None:
        upd["side-rear-display"] = _display_block_to_toml_section(body.side_rear_display)
    if body.rear_display is not None:
        upd["rear-display"] = _display_block_to_toml_section(body.rear_display)
    if body.ticker_board is not None:
        upd["ticker-board"] = _display_block_to_toml_section(body.ticker_board)
    return upd


class AppState:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config: MultiLedConfig = load_multi_led_config(config_path)
        self.route_first: str = ""
        self.route_second: str = ""
        self.route_third: str = ""
        self.ticker_first: str = ""
        self.ticker_second: str = ""


def create_app(config_path: Optional[Path] = None) -> FastAPI:
    path = config_path or DEFAULT_CONFIG_PATH
    state = AppState(path)

    app = FastAPI(title="LED displays CAN service", version="1")

    @app.get("/api/ping", response_model=PingResponse, response_model_by_alias=True)
    def ping() -> PingResponse:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
        return PingResponse(running="OK", timestamp_utc=ts)

    @app.post("/api/leddisplays/v1/config/set")
    async def config_set(body: ConfigSetBody) -> dict[str, str]:
        if body.color is not None:
            try:
                parse_color_name(body.color)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

        updates = _config_set_body_to_toml_updates(body)
        if not updates:
            return {"status": "noop"}

        merged = merge_config_file_with_updates(state.config_path, updates)
        write_merged_config_toml(state.config_path, merged)
        state.config = load_multi_led_config(state.config_path)
        return {"status": "ok"}

    @app.post("/api/leddisplays/v1/route/set")
    async def route_set(body: RouteSetBody) -> dict[str, str]:
        state.route_first = body.first_string
        state.route_second = body.second_string
        state.route_third = body.third_string
        json_route = route_json_internal(
            body.first_string,
            body.second_string,
            body.third_string,
        )

        async def _job() -> None:
            await asyncio.to_thread(send_route_to_all_displays, state.config, json_route)

        asyncio.create_task(_job())
        return {"status": "accepted"}

    @app.get(
        "/api/leddisplays/v1/route/set",
        response_model=RouteGetResponse,
        response_model_by_alias=True,
    )
    def route_get() -> RouteGetResponse:
        return RouteGetResponse(
            first_string=state.route_first,
            second_string=state.route_second,
            third_string=state.route_third,
        )

    @app.post("/api/leddisplays/v1/tickerboard/set")
    async def ticker_set(body: TickerSetBody) -> dict[str, str]:
        state.ticker_first = body.first_string
        state.ticker_second = body.second_string
        json_t = ticker_json_internal(body.first_string, body.second_string)

        async def _job() -> None:
            await asyncio.to_thread(send_ticker_to_board, state.config, json_t)

        asyncio.create_task(_job())
        return {"status": "accepted"}

    return app


app = create_app()
