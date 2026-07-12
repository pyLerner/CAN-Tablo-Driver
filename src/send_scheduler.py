"""
Сериализованная отправка на табло: coalescing, дедупликация, min_interval.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from led_config import MultiLedConfig, load_multi_led_config
from led_service import DisplayTransport

LOGGER = logging.getLogger("can-tablo")


class DisplaySendScheduler:
    """Один asyncio-воркер: last-write-wins coalesce, last_sent, min_interval."""

    def __init__(
        self,
        cfg: MultiLedConfig,
        *,
        send_fn: Optional[Callable[[MultiLedConfig, dict[str, str], DisplayTransport], None]] = None,
    ) -> None:
        self._cfg = cfg
        self._send_fn = send_fn or self._default_send
        self._pending: Optional[dict[str, str]] = None
        self._last_sent: Optional[dict[str, str]] = None
        self._last_send_monotonic: float = 0.0
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._transport = DisplayTransport()

    @staticmethod
    def _default_send(
        cfg: MultiLedConfig,
        values: dict[str, str],
        transport: DisplayTransport,
    ) -> None:
        transport.send_display_values(cfg, values)

    def start(self) -> None:
        if self._worker_task is not None:
            return
        self._stop.clear()
        self._worker_task = asyncio.create_task(self._worker_loop(), name="display-send-worker")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker_task is not None:
            await self._worker_task
            self._worker_task = None
        await asyncio.to_thread(self._transport.close)

    def update_config(self, cfg: MultiLedConfig) -> None:
        self._cfg = cfg

    def submit(self, values: dict[str, str]) -> None:
        normalized = {str(k): str(v) for k, v in values.items()}
        self._pending = normalized
        LOGGER.debug("coalesce: pending обновлён (%d зон)", len(normalized))
        self._wake.set()

    async def _worker_loop(self) -> None:
        await asyncio.to_thread(self._ensure_transport_open)
        try:
            while not self._stop.is_set():
                await self._wake.wait()
                if self._stop.is_set():
                    break
                while self._pending is not None and not self._stop.is_set():
                    await self._process_pending()
                if self._pending is None:
                    self._wake.clear()
        finally:
            await asyncio.to_thread(self._transport.close)

    def _ensure_transport_open(self) -> None:
        if not self._transport.is_open:
            cfg = load_multi_led_config(self._cfg.config_path)
            self._cfg = cfg
            self._transport.open(cfg)

    async def _process_pending(self) -> None:
        while self._pending is not None and not self._stop.is_set():
            values = self._pending
            self._pending = None

            await self._wait_min_interval()

            if self._pending is not None:
                continue

            if self._should_skip(values):
                LOGGER.info("пропуск дубликата (on_duplicate=skip)")
                if self._pending is not None:
                    continue
                return

            LOGGER.info("отправка values (%d зон)", len(values))
            try:
                await asyncio.to_thread(self._send_fn, self._cfg, values, self._transport)
            except Exception:
                LOGGER.exception("ошибка отправки на табло")
                raise
            self._last_sent = dict(values)
            self._last_send_monotonic = time.monotonic()
            LOGGER.debug("отправка завершена")

    async def _wait_min_interval(self) -> None:
        interval_ms = self._cfg.send_min_interval_ms
        if interval_ms <= 0:
            return
        if self._last_send_monotonic <= 0:
            return
        elapsed_ms = (time.monotonic() - self._last_send_monotonic) * 1000.0
        remaining_ms = interval_ms - elapsed_ms
        if remaining_ms <= 0:
            return
        LOGGER.debug("ожидание min_interval: %.0f мс", remaining_ms)
        deadline = time.monotonic() + remaining_ms / 1000.0
        while not self._stop.is_set():
            if self._pending is not None:
                return
            now = time.monotonic()
            if now >= deadline:
                return
            await asyncio.sleep(min(0.05, deadline - now))

    def _should_skip(self, values: dict[str, str]) -> bool:
        if self._cfg.send_on_duplicate == "send":
            return False
        return self._last_sent is not None and values == self._last_sent
