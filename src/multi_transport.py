"""
Один CAN Bus и несколько ISO-TP стеков (NotifierBasedCanStack) для разных пар tx/rx.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

try:
    import can
    import isotp
except ImportError:  # pragma: no cover
    can = None
    isotp = None


class MultiIsoTpTransport:
    """
    Общая шина + NotifierBasedCanStack на каждую пару (tx_id, rx_id).
    """

    def __init__(
        self,
        channel: str,
        bitrate: int,
        id_pairs: list[tuple[int, int]],
        iso_tp_params: Optional[dict[str, int]] = None,
    ) -> None:
        if can is None or isotp is None:
            raise RuntimeError("Для работы с CAN установите зависимости: python-can и can-isotp")
        if not id_pairs:
            raise ValueError("Нужна хотя бы одна пара sender_tx_id / sender_rx_id")

        params = iso_tp_params or {
            "rx_flowcontrol_timeout": 5000,
            "rx_consecutive_frame_timeout": 5000,
            "stmin": 10,
            "blocksize": 8,
        }

        self._channel = channel
        self._bitrate = bitrate
        self._params = params
        self._lock = threading.Lock()

        self.bus = can.interface.Bus(
            interface="socketcan",
            channel=channel,
            bitrate=bitrate,
        )
        self.notifier = can.Notifier(self.bus, [], timeout=0.001)

        self._stacks: dict[tuple[int, int], Any] = {}
        for tx_id, rx_id in id_pairs:
            addr = isotp.Address(isotp.AddressingMode.Normal_29bits, txid=tx_id, rxid=rx_id)
            stack = isotp.NotifierBasedCanStack(
                self.bus,
                self.notifier,
                address=addr,
                params=params,
            )
            stack.start()
            self._stacks[(tx_id, rx_id)] = stack

    def send(self, tx_id: int, rx_id: int, payload: bytes) -> None:
        key = (tx_id, rx_id)
        if key not in self._stacks:
            raise KeyError(f"Нет стека для tx={tx_id:#x} rx={rx_id:#x}")
        stack = self._stacks[key]
        with self._lock:
            stack.send(payload)
        # Стек после start() обрабатывает FC/CF во внутреннем потоке; без ожидания
        # `with MultiIsoTpTransport()` закрывает шину, пока многокадровая передача ещё не завершена.
        while stack.transmitting():
            time.sleep(max(0.0001, float(stack.sleep_time())))

    def close(self) -> None:
        for stack in self._stacks.values():
            try:
                stack.stop()
            except Exception:
                pass
        self._stacks.clear()
        try:
            self.notifier.stop()
        except Exception:
            pass
        try:
            self.bus.shutdown()
        except Exception:
            pass

    def __enter__(self) -> "MultiIsoTpTransport":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


class BoundMultiIsoTp:
    """Привязка MultiIsoTpTransport к одной паре tx/rx для IsoTpSender."""

    def __init__(self, multi: MultiIsoTpTransport, tx_id: int, rx_id: int) -> None:
        self._multi = multi
        self._tx = tx_id
        self._rx = rx_id

    def send(self, payload: bytes) -> None:
        self._multi.send(self._tx, self._rx, payload)
