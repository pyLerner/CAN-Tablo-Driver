"""Тесты DisplaySendScheduler: coalesce, дедупликация, min_interval."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from led_config import MultiLedConfig, load_multi_led_config  # noqa: E402
from led_service import DisplayTransport  # noqa: E402
from send_scheduler import DisplaySendScheduler  # noqa: E402


@pytest.fixture
def base_cfg() -> MultiLedConfig:
    return load_multi_led_config(SRC / "config.toml")


def _make_scheduler(
    cfg: MultiLedConfig,
    send_calls: list[dict[str, str]],
) -> DisplaySendScheduler:
    def _capture_send(
        _cfg: MultiLedConfig,
        values: dict[str, str],
        _transport: DisplayTransport,
    ) -> None:
        send_calls.append(dict(values))

    return DisplaySendScheduler(cfg, send_fn=_capture_send)


async def _run_scheduler(
    scheduler: DisplaySendScheduler,
    fn: Any,
    timeout: float = 2.0,
) -> None:
    with patch.object(scheduler, "_ensure_transport_open"):
        scheduler.start()
        try:
            await asyncio.wait_for(fn(), timeout=timeout)
            await asyncio.sleep(0.05)
        finally:
            with patch.object(scheduler._transport, "close"):
                await scheduler.stop()


def _run(coro: Any) -> None:
    asyncio.run(coro)


def test_coalesce_last_write_wins(base_cfg: MultiLedConfig) -> None:
    send_calls: list[dict[str, str]] = []
    scheduler = _make_scheduler(base_cfg, send_calls)

    async def _job() -> None:
        for i in range(5):
            scheduler.submit({"1": f"v{i}"})
        await asyncio.sleep(0.2)

    _run(_run_scheduler(scheduler, _job))
    assert len(send_calls) == 1
    assert send_calls[0] == {"1": "v4"}


def test_skip_duplicate(base_cfg: MultiLedConfig) -> None:
    send_calls: list[dict[str, str]] = []
    cfg = replace(base_cfg, send_on_duplicate="skip", send_min_interval_ms=0)
    scheduler = _make_scheduler(cfg, send_calls)

    async def _job() -> None:
        scheduler.submit({"1": "same"})
        await asyncio.sleep(0.15)
        scheduler.submit({"1": "same"})
        await asyncio.sleep(0.15)

    _run(_run_scheduler(scheduler, _job))
    assert len(send_calls) == 1


def test_send_duplicate(base_cfg: MultiLedConfig) -> None:
    send_calls: list[dict[str, str]] = []
    cfg = replace(base_cfg, send_on_duplicate="send", send_min_interval_ms=0)
    scheduler = _make_scheduler(cfg, send_calls)

    async def _job() -> None:
        scheduler.submit({"1": "same"})
        await asyncio.sleep(0.15)
        scheduler.submit({"1": "same"})
        await asyncio.sleep(0.15)

    _run(_run_scheduler(scheduler, _job))
    assert len(send_calls) == 2


def test_min_interval(base_cfg: MultiLedConfig) -> None:
    send_calls: list[dict[str, str]] = []
    cfg = replace(base_cfg, send_on_duplicate="send", send_min_interval_ms=200)
    scheduler = _make_scheduler(cfg, send_calls)

    async def _job() -> None:
        scheduler.submit({"1": "first"})
        await asyncio.sleep(0.05)
        scheduler.submit({"1": "second"})
        await asyncio.sleep(0.5)

    _run(_run_scheduler(scheduler, _job, timeout=3.0))
    assert len(send_calls) == 2
    assert send_calls[0] == {"1": "first"}
    assert send_calls[1] == {"1": "second"}


def test_coalesce_during_interval(base_cfg: MultiLedConfig) -> None:
    send_calls: list[dict[str, str]] = []
    cfg = replace(base_cfg, send_on_duplicate="send", send_min_interval_ms=200)
    scheduler = _make_scheduler(cfg, send_calls)

    async def _job() -> None:
        scheduler.submit({"1": "first"})
        await asyncio.sleep(0.05)
        scheduler.submit({"1": "during-wait-1"})
        await asyncio.sleep(0.05)
        scheduler.submit({"1": "during-wait-2"})
        await asyncio.sleep(0.5)

    _run(_run_scheduler(scheduler, _job, timeout=3.0))
    assert len(send_calls) == 2
    assert send_calls[0] == {"1": "first"}
    assert send_calls[1] == {"1": "during-wait-2"}


def test_parse_send_on_duplicate_invalid() -> None:
    from led_config import _parse_send_on_duplicate

    with pytest.raises(ValueError, match="on_duplicate"):
        _parse_send_on_duplicate("force")
