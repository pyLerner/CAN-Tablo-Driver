"""
Драйвер LED-табло с передачей данных по CAN/ISO-TP (29-bit ID).

Пайплайн отправителя:
JSON -> текст -> растровая область -> payload -> CAN ISO-TP

Пайплайн приемника:
CAN ISO-TP -> payload -> декодирование области -> изображение -> сохранение

Формат payload области:
- 2 байта: тип операции (0x0001 = заливка прямоугольной области по маске)
- 2 байта: X
- 2 байта: Y
- 2 байта: width
- 2 байта: height
- 1 байт: код НЕчерного цвета
- N байт: битовая маска пикселей области (строка за строкой)
  * 0 -> черный пиксель
  * 1 -> нечерный пиксель (цвет из поля color_non_black)
  * неиспользуемые хвостовые биты последнего байта = 0
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import math
import threading
import time
import tomllib
import types
from queue import Empty, Queue
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

try:
    import can
    from can.io.canutils import CanutilsLogWriter
    import isotp
except ImportError:  # pragma: no cover - полезно для локальной проверки без CAN-зависимостей
    can = None
    isotp = None
    CanutilsLogWriter = None


# ============================================================
# КОНСТАНТЫ ПРОТОКОЛА И ЦВЕТА
# ============================================================

OP_FILL_RECT_MASK = 0x0001

COLOR_BLACK = 0x00
COLOR_RED = 0x01
COLOR_GREEN = 0x02
COLOR_BLUE = 0x04
COLOR_YELLOW = 0x03
COLOR_CYAN = 0x06
COLOR_MAGENTA = 0x05
COLOR_WHITE = 0x07

COLOR_CODE_TO_RGB: dict[int, tuple[int, int, int]] = {
    COLOR_BLACK: (0, 0, 0),
    COLOR_RED: (255, 0, 0),
    COLOR_GREEN: (0, 255, 0),
    COLOR_BLUE: (0, 0, 255),
    COLOR_YELLOW: (255, 255, 0),
    COLOR_CYAN: (0, 255, 255),
    COLOR_MAGENTA: (255, 0, 255),
    COLOR_WHITE: (255, 255, 255),
}

HEADER_SIZE_BYTES = 11

LOGGER = logging.getLogger("can-tablo")


@dataclass(slots=True)
class AppConfig:
    """
    Конфигурация приложения, загружаемая из TOML.
    """

    can_channel: str
    can_bitrate: int
    slcan_tty_baudrate: int
    slcan_sleep_after_open: float
    slcan_read_timeout: float
    slcan_open_timeout_sec: float
    sender_tx_id: int
    sender_rx_id: int
    iso_tp_params: dict[str, int]
    use_stack_sleep_time: bool
    loop_sleep_sec: float
    logs_dir: Path
    log_filename: str
    candump_log_path: Optional[Path]
    log_backup_count: int
    log_max_bytes: int
    route_width: int
    route_text_scale_x: float
    tablo_width: int
    tablo_height: int
    pad_left: int
    pad_right: int
    pad_top: int
    pad_bottom: int
    text_in_path: Path
    font_path: Path


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def u16le(value: int) -> bytes:
    """
    Преобразует целое число в 2 байта uint16 little-endian.

    Args:
        value: Значение в диапазоне 0..65535.

    Returns:
        Байтовое представление значения.
    """
    return int(value).to_bytes(2, byteorder="little", signed=False)


def read_u16le(payload: bytes, offset: int) -> int:
    """
    Считывает uint16 little-endian из payload по смещению.

    Args:
        payload: Входной буфер.
        offset: Позиция первого байта числа.

    Returns:
        Декодированное целое значение.
    """
    return int.from_bytes(payload[offset : offset + 2], byteorder="little", signed=False)


def payload_to_hex(payload: bytes) -> str:
    """
    Преобразует payload в читаемый HEX-вид.

    Args:
        payload: Последовательность байтов.

    Returns:
        Строка вида "AA BB CC ...".
    """
    return " ".join(f"{byte:02X}" for byte in payload)


def bitmask_size(width: int, height: int) -> int:
    """
    Вычисляет размер битовой маски в байтах для области width x height.

    Args:
        width: Ширина области.
        height: Высота области.

    Returns:
        Количество байтов, достаточное для хранения всех битов пикселей.
    """
    return math.ceil((width * height) / 8)


def setup_logging(log_dir: Path, filename: str, max_bytes: int, backup_count: int) -> None:
    """
    Настраивает логирование в файл с ротацией.

    Args:
        log_dir: Директория, где будут храниться логи.
        filename: Имя основного файла лога.
        max_bytes: Максимальный размер файла до ротации.
        backup_count: Количество архивных файлов.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / filename

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    rotating_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    rotating_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    LOGGER.addHandler(rotating_handler)
    LOGGER.addHandler(console_handler)
    LOGGER.propagate = False


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    """
    Преобразует путь из конфигурации в абсолютный.

    Относительные пути интерпретируются относительно директории TOML-файла.
    """
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_app_config(config_path: Path) -> AppConfig:
    """
    Загружает конфигурацию приложения из TOML.

    Args:
        config_path: Путь к TOML-файлу.

    Returns:
        Объект `AppConfig` с параметрами запуска.
    """
    with config_path.open("rb") as file:
        raw: dict[str, Any] = tomllib.load(file)

    base_dir = config_path.resolve().parent

    can_cfg = raw.get("can", {})
    iso_tp_cfg = raw.get("iso-tp", {})
    logs_cfg = raw.get("logs", {})
    tablo_cfg = raw.get("tabloRouteTwoStrings", {})
    text_in_cfg = raw.get("TextIn", {})

    iso_tp_params = {
        "rx_flowcontrol_timeout": int(iso_tp_cfg.get("rx_flowcontrol_timeout", 5000)),
        "rx_consecutive_frame_timeout": int(iso_tp_cfg.get("rx_consecutive_frame_timeout", 5000)),
        "stmin": int(iso_tp_cfg.get("stmin", 10)),
        "blocksize": int(iso_tp_cfg.get("blocksize", 8)),
    }
    logs_dir = resolve_path(base_dir, str(logs_cfg.get("dir", "./logs")))
    candump_file = str(logs_cfg.get("candump_file", "../logs/candump.log")).strip()
    candump_log_path = (
        resolve_path(base_dir, candump_file) if candump_file else None
    )

    return AppConfig(
        can_channel=str(can_cfg.get("channel", "can0")),
        can_bitrate=int(can_cfg.get("bitrate", 500_000)),
        slcan_tty_baudrate=int(can_cfg.get("slcan_tty_baudrate", 115_200)),
        slcan_sleep_after_open=float(can_cfg.get("slcan_sleep_after_open", 0.2)),
        slcan_read_timeout=float(can_cfg.get("slcan_read_timeout", 0.05)),
        slcan_open_timeout_sec=float(can_cfg.get("slcan_open_timeout_sec", 8.0)),
        sender_tx_id=int(can_cfg.get("sender_tx_id", 0x18EF1001)),
        sender_rx_id=int(can_cfg.get("sender_rx_id", 0x18EF1101)),
        iso_tp_params=iso_tp_params,
        use_stack_sleep_time=bool(iso_tp_cfg.get("use_stack_sleep_time", True)),
        loop_sleep_sec=float(iso_tp_cfg.get("loop_sleep_sec", 0.0001)),
        logs_dir=logs_dir,
        log_filename=str(logs_cfg.get("file", "tablo.log")),
        candump_log_path=candump_log_path,
        log_backup_count=int(logs_cfg.get("count", 5)),
        log_max_bytes=int(logs_cfg.get("max_size", 1_048_576)),
        route_width=int(tablo_cfg.get("route_width", 80)),
        route_text_scale_x=float(tablo_cfg.get("route_text_scale_x", 1.0)),
        tablo_width=int(tablo_cfg.get("width", 192)),
        tablo_height=int(tablo_cfg.get("height", 64)),
        pad_left=int(tablo_cfg.get("pad_left", 0)),
        pad_right=int(tablo_cfg.get("pad_right", 0)),
        pad_top=int(tablo_cfg.get("pad_top", 2)),
        pad_bottom=int(tablo_cfg.get("pad_bottom", 2)),
        text_in_path=resolve_path(base_dir, str(text_in_cfg.get("path", "./text-in.json"))),
        font_path=resolve_path(base_dir, str(text_in_cfg.get("font", "./DejaVuSans.ttf"))),
    )


def load_text_json(path: Path) -> str:
    """
    Читает JSON с текстом для отправки и возвращает исходную строку.

    Одновременно выполняется проверка корректности JSON.
    """
    content = path.read_text(encoding="utf-8")
    json.loads(content)
    return content


# ============================================================
# РЕНДЕРИНГ ТЕКСТА В МОНОХРОМНУЮ ОБЛАСТЬ
# ============================================================


class TextRenderer:
    """
    Рендерит текст в изображение фиксированного размера с TTF-шрифтом.

    Выходной формат изображения: `L` (градации серого), где:
    - 0: черный фон
    - 255: символы
    """

    def __init__(self, font_path: str) -> None:
        self.font_path = font_path

    def render(
        self,
        text: str,
        size: Tuple[int, int],
        pad: int,
        horizontal_scale: float = 1.0,
    ) -> Image.Image:
        """
        Создает изображение области и рисует текст по центру по горизонтали.

        Args:
            text: Текст для вывода.
            size: Размер области `(width, height)`.
            pad: Вертикальный отступ сверху/снизу, влияющий на размер шрифта.
            horizontal_scale: Горизонтальный масштаб текста.
                `1.0` — без изменения, `>1.0` — растяжение, `<1.0` — сжатие.

        Returns:
            Объект `PIL.Image` в режиме `L`.
        """
        width, height = size
        text_height = max(1, height - 2 * pad)
        safe_scale = max(0.01, horizontal_scale)

        image = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(image)

        font = ImageFont.truetype(self.font_path, text_height)
        bbox = draw.textbbox((0, 0), text, font=font)

        text_width = bbox[2] - bbox[0]
        text_height_bbox = bbox[3] - bbox[1]

        # Рендерим текст в отдельный слой, чтобы масштабировать только ось X.
        text_layer = Image.new("L", (max(1, text_width), max(1, text_height_bbox)), 0)
        text_layer_draw = ImageDraw.Draw(text_layer)
        text_layer_draw.text((-bbox[0], -bbox[1]), text, fill=255, font=font)

        if abs(safe_scale - 1.0) > 1e-6:
            scaled_width = max(1, int(round(text_layer.width * safe_scale)))
            text_layer = text_layer.resize(
                (scaled_width, text_layer.height),
                resample=Image.Resampling.BICUBIC,
            )

        x_pos = max(0, (width - text_layer.width) // 2)
        y_pos = max(0, (height - text_height_bbox) // 2)

        image.paste(text_layer, (x_pos, y_pos))
        return image


# ============================================================
# ПРОТОКОЛ ОБЛАСТИ: КОДИРОВАНИЕ/ДЕКОДИРОВАНИЕ
# ============================================================


@dataclass(slots=True)
class RectMaskPacket:
    """
    Модель payload для операции заливки области по битовой маске.

    Поля соответствуют формату сообщения:
    `op(2) + x(2) + y(2) + width(2) + height(2) + color(1) + bitmask(N)`.
    """

    op_code: int
    x: int
    y: int
    width: int
    height: int
    color_non_black: int
    mask: bytes

    def validate(self) -> None:
        """
        Проверяет внутреннюю корректность структуры пакета.

        Raises:
            ValueError: Если найдено несовпадение размеров или некорректные поля.
        """
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Размер области должен быть положительным")

        if self.op_code != OP_FILL_RECT_MASK:
            raise ValueError(f"Неподдерживаемая операция: {self.op_code:#06x}")

        expected_mask_size = bitmask_size(self.width, self.height)
        if len(self.mask) != expected_mask_size:
            raise ValueError(
                f"Некорректная длина маски: {len(self.mask)}, ожидается {expected_mask_size}"
            )

    @classmethod
    def from_image(
        cls,
        x: int,
        y: int,
        image: Image.Image,
        color_non_black: int = COLOR_YELLOW,
        threshold: int = 128,
    ) -> "RectMaskPacket":
        """
        Создает пакет из изображения области.

        Правила преобразования пикселей:
        - Яркость <= threshold -> бит 0 (черный)
        - Яркость > threshold -> бит 1 (нечерный)

        Биты записываются последовательно по строкам (row-major),
        внутри байта используется порядок от старшего бита к младшему (MSB-first).

        Args:
            x: Координата X области.
            y: Координата Y области.
            image: Изображение области (будет приведено к `L`).
            color_non_black: Код нечерного цвета (1 байт).
            threshold: Порог бинаризации.

        Returns:
            Сформированный объект пакета.
        """
        gray = image.convert("L")
        width, height = gray.size
        total_pixels = width * height
        mask = bytearray(bitmask_size(width, height))

        pixels = gray.load()
        for py in range(height):
            for px in range(width):
                pixel_index = py * width + px
                byte_index = pixel_index // 8
                bit_index_in_byte = 7 - (pixel_index % 8)

                if pixels[px, py] > threshold:
                    mask[byte_index] |= 1 << bit_index_in_byte

        return cls(
            op_code=OP_FILL_RECT_MASK,
            x=x,
            y=y,
            width=width,
            height=height,
            color_non_black=color_non_black,
            mask=bytes(mask),
        )

    def to_payload(self) -> bytes:
        """
        Сериализует пакет в бинарный payload для отправки по ISO-TP.

        Returns:
            Готовый payload.
        """
        self.validate()

        payload = bytearray()
        payload += u16le(self.op_code)
        payload += u16le(self.x)
        payload += u16le(self.y)
        payload += u16le(self.width)
        payload += u16le(self.height)
        payload.append(self.color_non_black & 0xFF)
        payload += self.mask
        return bytes(payload)

    @classmethod
    def from_payload(cls, payload: bytes) -> "RectMaskPacket":
        """
        Декодирует бинарный payload в структуру пакета.

        Args:
            payload: Входные данные ISO-TP.

        Returns:
            Декодированный объект `RectMaskPacket`.

        Raises:
            ValueError: При некорректной длине/формате payload.
        """
        if len(payload) < HEADER_SIZE_BYTES:
            raise ValueError("Payload слишком короткий для заголовка")

        op_code = read_u16le(payload, 0)
        x = read_u16le(payload, 2)
        y = read_u16le(payload, 4)
        width = read_u16le(payload, 6)
        height = read_u16le(payload, 8)
        color_non_black = payload[10]

        expected_mask_size = bitmask_size(width, height)
        expected_total = HEADER_SIZE_BYTES + expected_mask_size
        if len(payload) != expected_total:
            raise ValueError(
                f"Некорректная длина payload: {len(payload)}, ожидается {expected_total}"
            )

        packet = cls(
            op_code=op_code,
            x=x,
            y=y,
            width=width,
            height=height,
            color_non_black=color_non_black,
            mask=payload[HEADER_SIZE_BYTES:],
        )
        packet.validate()
        return packet

    def to_image(self) -> Image.Image:
        """
        Восстанавливает цветное изображение области из битовой маски.

        Returns:
            Изображение `RGB` размером `width x height`.
        """
        self.validate()

        image = Image.new("RGB", (self.width, self.height), COLOR_CODE_TO_RGB[COLOR_BLACK])
        pixels = image.load()
        color = COLOR_CODE_TO_RGB.get(self.color_non_black, (255, 255, 255))

        total_pixels = self.width * self.height
        for pixel_index in range(total_pixels):
            byte_index = pixel_index // 8
            bit_index_in_byte = 7 - (pixel_index % 8)
            is_on = (self.mask[byte_index] >> bit_index_in_byte) & 0x01

            if is_on:
                py = pixel_index // self.width
                px = pixel_index % self.width
                pixels[px, py] = color

        return image


# ============================================================
# CAN ISO-TP ТРАНСПОРТ
# ============================================================


class CandumpTeeLogger:
    """
    Логирует CAN кадры в формате, совместимом с `candump -L`.

    Используется внутри одного процесса, чтобы не открывать /dev/ttyACM0
    вторым приложением.
    """

    def __init__(self, log_path: Path, channel: str) -> None:
        if CanutilsLogWriter is None:
            raise RuntimeError("CanutilsLogWriter недоступен (python-can не установлен)")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Создаем файл сразу, даже если до первого кадра приложение завершится ошибкой.
        log_path.touch(exist_ok=True)
        self._writer = CanutilsLogWriter(str(log_path), channel=channel, append=True)
        self._closed = False

    def log_rx(self, msg: Any) -> None:
        self._writer.on_message_received(msg)
        self._writer.file.flush()

    def log_tx(self, msg: Any) -> None:
        tx_msg = msg.__copy__()
        tx_msg.is_rx = False
        tx_msg.timestamp = time.time()
        self._writer.on_message_received(tx_msg)
        self._writer.file.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._writer.stop()
        self._closed = True


class CanIsoTpTransport:
    """
    Универсальный транспортный адаптер для передачи/приема ISO-TP поверх SocketCAN.

    Используется режим расширенной адресации CAN ID (29-bit): `Normal_29bits`.
    """

    def __init__(
        self,
        channel: str,
        bitrate: int,
        slcan_tty_baudrate: int,
        slcan_sleep_after_open: float,
        slcan_read_timeout: float,
        slcan_open_timeout_sec: float,
        tx_id: int,
        rx_id: int,
        iso_tp_params: Optional[dict[str, int]] = None,
        use_stack_sleep_time: bool = True,
        loop_sleep_sec: float = 0.0001,
        candump_log_path: Optional[Path] = None,
        on_receive: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        if can is None or isotp is None:
            raise RuntimeError(
                "Для работы с CAN установите зависимости: python-can и can-isotp"
            )

        self._candump_logger: Optional[CandumpTeeLogger] = None
        if candump_log_path is not None:
            try:
                self._candump_logger = CandumpTeeLogger(candump_log_path, channel=channel)
                LOGGER.info("CAN candump-лог включен: %s", candump_log_path)
            except Exception as exc:
                self._candump_logger = None
                LOGGER.error("Не удалось включить candump-лог (%s): %s", candump_log_path, exc)

        LOGGER.info(
            "Открытие CAN интерфейса: slcan channel=%s bitrate=%d tty_baud=%d open_timeout=%.1fs",
            channel,
            bitrate,
            slcan_tty_baudrate,
            slcan_open_timeout_sec,
        )
        try:
            raw_bus = self._open_slcan_bus_with_timeout(
                channel=channel,
                bitrate=bitrate,
                tty_baudrate=slcan_tty_baudrate,
                sleep_after_open=slcan_sleep_after_open,
                timeout=slcan_read_timeout,
                open_timeout_sec=slcan_open_timeout_sec,
            )
        except Exception:
            if self._candump_logger is not None:
                self._candump_logger.close()
            raise
        LOGGER.info("CAN интерфейс открыт: %s", channel)

        self.bus = raw_bus
        if self._candump_logger is not None:
            self._install_candump_hooks(self.bus, self._candump_logger)

        self.stack = isotp.CanStack(
            bus=self.bus,
            address=isotp.Address(isotp.AddressingMode.Normal_29bits, txid=tx_id, rxid=rx_id),
            params=iso_tp_params
            or {
                # На реальной шине can0 возможны задержки из-за арбитража и фонового трафика.
                # Увеличиваем таймауты, чтобы не рвать передачу крупных payload.
                "rx_flowcontrol_timeout": 5000,
                "rx_consecutive_frame_timeout": 5000,
                # Просим отправителя выдерживать паузу между Consecutive Frame,
                # чтобы исключить потери кадров на перегруженной шине/CPU.
                "stmin": 10,
                "blocksize": 8,
            },
        )

        self.on_receive = on_receive
        self.use_stack_sleep_time = use_stack_sleep_time
        self.loop_sleep_sec = max(0.0, loop_sleep_sec)
        self._running = False
        self._rx_thread: Optional[threading.Thread] = None
        self._cb_thread: Optional[threading.Thread] = None
        self._rx_queue: "Queue[Optional[bytes]]" = Queue()

    def _sleep_tick(self) -> None:
        """
        Пауза между итерациями обработки ISO-TP.

        Если `use_stack_sleep_time=True`, используется рекомендованное библиотекой
        значение `self.stack.sleep_time()`. Иначе применяется фиксированная пауза
        `loop_sleep_sec` из конфигурации.
        """
        if self.use_stack_sleep_time:
            sleep_value = self.stack.sleep_time()
            time.sleep(max(0.0, float(sleep_value)))
            return
        time.sleep(self.loop_sleep_sec)

    @staticmethod
    def _install_candump_hooks(bus: Any, candump_logger: CandumpTeeLogger) -> None:
        """
        Добавляет логирование TX/RX, не меняя тип объекта шины.
        Это важно: `isotp.CanStack` проверяет, что передан именно `BusABC`.
        """
        orig_send = bus.send
        orig_recv = bus.recv

        def send_with_log(self: Any, msg: Any, timeout: Optional[float] = None) -> Any:
            candump_logger.log_tx(msg)
            return orig_send(msg, timeout=timeout)

        def recv_with_log(self: Any, timeout: Optional[float] = None) -> Any:
            msg = orig_recv(timeout)
            if msg is not None:
                candump_logger.log_rx(msg)
            return msg

        bus.send = types.MethodType(send_with_log, bus)
        bus.recv = types.MethodType(recv_with_log, bus)

    @staticmethod
    def _open_slcan_bus_with_timeout(
        channel: str,
        bitrate: int,
        tty_baudrate: int,
        sleep_after_open: float,
        timeout: float,
        open_timeout_sec: float,
    ) -> Any:
        result_queue: "Queue[tuple[str, Any]]" = Queue(maxsize=1)

        def worker() -> None:
            try:
                bus_obj = can.interface.Bus(
                    interface="slcan",
                    channel=channel,
                    bitrate=bitrate,
                    tty_baudrate=tty_baudrate,
                    sleep_after_open=sleep_after_open,
                    timeout=timeout,
                )
                result_queue.put(("ok", bus_obj))
            except Exception as exc:  # pragma: no cover - диагностическая ветка
                result_queue.put(("err", exc))

        open_thread = threading.Thread(target=worker, daemon=True)
        open_thread.start()
        open_thread.join(timeout=max(0.1, open_timeout_sec))

        if open_thread.is_alive():
            raise TimeoutError(
                f"Таймаут открытия slcan интерфейса ({open_timeout_sec:.1f}s) "
                f"для {channel}. Проверьте занятость порта и SLCAN-совместимость адаптера."
            )

        try:
            status, value = result_queue.get_nowait()
        except Empty as exc:  # pragma: no cover - защитная ветка
            raise RuntimeError("Не удалось получить результат открытия slcan интерфейса") from exc

        if status == "err":
            raise value
        return value

    def send(self, payload: bytes) -> None:
        """Отправляет один ISO-TP payload и дожидается завершения передачи."""
        self.stack.send(payload)
        tx_started_at = time.monotonic()
        while self.stack.transmitting():
            self.stack.process()
            self._sleep_tick()
            if time.monotonic() - tx_started_at > 30.0:
                LOGGER.error(
                    "Ожидание завершения ISO-TP передачи > 30с (payload=%d байт). "
                    "Прерываем ожидание.",
                    len(payload),
                )
                break

    def start(self) -> None:
        """Запускает фоновый поток приема."""
        self._running = True
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()

        # Колбэк обрабатывается отдельно, чтобы не тормозить прием CAN-кадров.
        if self.on_receive is not None:
            self._cb_thread = threading.Thread(target=self._callback_loop, daemon=True)
            self._cb_thread.start()

    def _rx_loop(self) -> None:
        """Внутренний цикл обработки входящих CAN кадров и сборки ISO-TP сообщений."""
        while self._running:
            self.stack.process()
            if self.stack.available():
                data = self.stack.recv()
                if data is not None:
                    self._rx_queue.put(data)
            self._sleep_tick()

    def _callback_loop(self) -> None:
        """Обрабатывает декодированные payload из очереди в отдельном потоке."""
        while self._running:
            try:
                data = self._rx_queue.get(timeout=0.1)
            except Empty:
                continue

            if data is None:
                break

            if self.on_receive is not None:
                self.on_receive(data)

    def close(self) -> None:
        """Останавливает прием и закрывает CAN-шину."""
        self._running = False
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=1)

        # Сигнал завершения для callback-потока.
        self._rx_queue.put(None)
        if self._cb_thread is not None:
            self._cb_thread.join(timeout=1)

        self.bus.shutdown()
        if self._candump_logger is not None:
            self._candump_logger.close()

    def __enter__(self) -> "CanIsoTpTransport":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# ============================================================
# БАЗОВОЕ ТАБЛО И КОНКРЕТНАЯ РАЗМЕТКА
# ============================================================


class AbstractTablo(ABC):
    """
    Базовый класс логики разбиения табло на области и отправки этих областей.
    """

    def __init__(
        self,
        width: int,
        height: int,
        pad_left: int,
        pad_right: int,
        pad_top: int,
        pad_bottom: int,
        renderer: TextRenderer,
        transport: CanIsoTpTransport,
    ) -> None:
        self.width = width
        self.height = height
        self.pad_left = pad_left
        self.pad_right = pad_right
        self.pad_top = pad_top
        self.pad_bottom = pad_bottom
        self.renderer = renderer
        self.transport = transport

    def render_region(
        self,
        text: str,
        x: int,
        y: int,
        width: int,
        height: int,
        color_non_black: int = COLOR_YELLOW,
        horizontal_scale: float = 1.0,
    ) -> None:
        """
        Полный цикл формирования и отправки одной области:
        текст -> bitmap -> пакет -> payload -> ISO-TP.
        """
        image = self.renderer.render(
            text,
            (width, height),
            self.pad_top,
            horizontal_scale=horizontal_scale,
        )
        packet = RectMaskPacket.from_image(
            x=x,
            y=y,
            image=image,
            color_non_black=color_non_black,
        )
        payload = packet.to_payload()
        self.transport.send(payload)

    @abstractmethod
    def send_to_tablo(self, json_data: str) -> None:
        """Формирует набор областей из входных данных и отправляет их на табло."""


class RouteAndTwoLinesTablo(AbstractTablo):
    """
    Макет табло из трех текстовых зон:
    - левый столбец: номер маршрута
    - справа сверху: строка 1
    - справа снизу: строка 2
    """

    def __init__(
        self,
        route_width: int,
        route_text_scale_x: float = 1.0,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.route_width = route_width
        self.route_text_scale_x = route_text_scale_x

    def send_to_tablo(self, json_data: str) -> None:
        data = json.loads(json_data)

        route = data.get("firstString", "")
        top = data.get("secondString", "")
        bottom = data.get("thirdString", "")

        usable_height = self.height - self.pad_top - self.pad_bottom
        half_height = usable_height // 2

        # 1) Область маршрута
        self.render_region(
            route, 
            self.pad_left, 
            self.pad_top, 
            self.route_width, 
            usable_height,
            horizontal_scale=self.route_text_scale_x,
        )

        # 2) Верхняя строка
        self.render_region(
            top,
            self.pad_left + self.route_width,
            self.pad_top,
            self.width - self.route_width - self.pad_right,
            half_height,
        )

        # 3) Нижняя строка
        self.render_region(
            bottom,
            self.pad_left + self.route_width,
            self.pad_top + half_height,
            self.width - self.route_width - self.pad_right,
            half_height,
        )


# ============================================================
# ЭМУЛЯТОР КОНТРОЛЛЕРА (ПРИЕМНИК)
# ============================================================


class MockController:
    """
    Эмулятор приемника:
    - принимает payload области,
    - декодирует заголовок и маску,
    - восстанавливает изображение,
    - сохраняет его в папку `logs/received`.
    """

    def __init__(self, output_dir: str = "logs/received") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def on_receive(self, payload: bytes) -> None:
        """
        Callback для `CanIsoTpTransport`.

        Args:
            payload: Полный ISO-TP payload с описанием области.
        """
        try:
            packet = RectMaskPacket.from_payload(payload)
        except ValueError as exc:
            LOGGER.error("Ошибка декодирования payload: %s", exc)
            LOGGER.error("RX HEX: %s", payload_to_hex(payload))
            return

        image = packet.to_image()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        image_name = (
            f"region_{timestamp}_x{packet.x}_y{packet.y}_w{packet.width}_h{packet.height}.png"
        )
        image_path = self.output_dir / image_name
        image.save(image_path)

        LOGGER.info(
            "Принято: op=0x%04X x=%d y=%d w=%d h=%d color=0x%02X mask_bytes=%d image=%s",
            packet.op_code,
            packet.x,
            packet.y,
            packet.width,
            packet.height,
            packet.color_non_black,
            len(packet.mask),
            image_path,
        )

        LOGGER.info(
            f"Получена байт строка:\n {payload_to_hex(payload=payload)}"
        )


# ============================================================
# ДЕМО-СЦЕНАРИИ
# ============================================================


def run_sender(config: AppConfig) -> None:
    """Отправляет текст из `text-in.json` на табло по CAN/ISO-TP."""
    renderer = TextRenderer(str(config.font_path))
    json_data = load_text_json(config.text_in_path)

    LOGGER.info("Отправка текста из %s", config.text_in_path)
    with CanIsoTpTransport(
        channel=config.can_channel,
        bitrate=config.can_bitrate,
        slcan_tty_baudrate=config.slcan_tty_baudrate,
        slcan_sleep_after_open=config.slcan_sleep_after_open,
        slcan_read_timeout=config.slcan_read_timeout,
        slcan_open_timeout_sec=config.slcan_open_timeout_sec,
        tx_id=config.sender_tx_id,
        rx_id=config.sender_rx_id,
        iso_tp_params=config.iso_tp_params,
        use_stack_sleep_time=config.use_stack_sleep_time,
        loop_sleep_sec=config.loop_sleep_sec,
        candump_log_path=config.candump_log_path,
    ) as transport:
        tablo = RouteAndTwoLinesTablo(
            route_width=config.route_width,
            route_text_scale_x=config.route_text_scale_x,
            width=config.tablo_width,
            height=config.tablo_height,
            pad_left=config.pad_left,
            pad_right=config.pad_right,
            pad_top=config.pad_top,
            pad_bottom=config.pad_bottom,
            renderer=renderer,
            transport=transport,
        )
        tablo.send_to_tablo(json_data)
        time.sleep(0.001)
    LOGGER.info("Отправка завершена")


def run_controller(config: AppConfig) -> None:
    """Запускает приемник ISO-TP и сохраняет принятые изображения областей."""
    images_dir = config.logs_dir / "received"
    controller = MockController(output_dir=str(images_dir))

    LOGGER.info(
        "Контроллер слушает %s (ISO-TP 29-bit), изображения: %s",
        config.can_channel,
        images_dir,
    )
    with CanIsoTpTransport(
        channel=config.can_channel,
        bitrate=config.can_bitrate,
        slcan_tty_baudrate=config.slcan_tty_baudrate,
        slcan_sleep_after_open=config.slcan_sleep_after_open,
        slcan_read_timeout=config.slcan_read_timeout,
        slcan_open_timeout_sec=config.slcan_open_timeout_sec,
        tx_id=config.sender_rx_id,
        rx_id=config.sender_tx_id,
        iso_tp_params=config.iso_tp_params,
        use_stack_sleep_time=config.use_stack_sleep_time,
        loop_sleep_sec=config.loop_sleep_sec,
        candump_log_path=config.candump_log_path,
        on_receive=controller.on_receive,
    ):
        while True:
            time.sleep(0.1)


def run_local_demo(config: AppConfig) -> None:
    """
    Локальная самопроверка без CAN:
    - рендер текста,
    - формирование payload,
    - декодирование payload,
    - сохранение восстановленного изображения.
    """
    renderer = TextRenderer(str(config.font_path))
    image = renderer.render("TEST", (76, 60), pad=2)

    packet_tx = RectMaskPacket.from_image(
        x=2,
        y=9,
        image=image,
        color_non_black=COLOR_YELLOW,
    )
    payload = packet_tx.to_payload()

    packet_rx = RectMaskPacket.from_payload(payload)
    restored = packet_rx.to_image()

    config.logs_dir.mkdir(parents=True, exist_ok=True)
    restored_path = config.logs_dir / "local-demo-restored.png"
    restored.save(restored_path)

    LOGGER.info("LOCAL DEMO payload bytes: %d", len(payload))
    LOGGER.info("LOCAL DEMO payload head: %s", payload_to_hex(payload[:32]))
    LOGGER.info("LOCAL DEMO restored image: %s", restored_path)


# ============================================================
# ТОЧКА ВХОДА
# ============================================================


def parse_args() -> argparse.Namespace:
    """
    Парсит аргументы CLI.

    Поддерживается выбор режима и путь к конфигурации.
    """
    parser = argparse.ArgumentParser(description="LED tablo CAN/ISO-TP driver")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("send", "recv", "demo"),
        default="send",
        help="Режим работы: send, recv или demo (по умолчанию send)",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="./config.toml",
        help="Путь к config.toml (по умолчанию ./config.toml)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_app_config(config_path)

    setup_logging(
        log_dir=config.logs_dir,
        filename=config.log_filename,
        max_bytes=config.log_max_bytes,
        backup_count=config.log_backup_count,
    )
    LOGGER.info("Запуск режима=%s, config=%s", args.mode, config_path)
    LOGGER.info(
        "Параметры CAN: channel=%s bitrate=%d tty_baud=%d candump=%s",
        config.can_channel,
        config.can_bitrate,
        config.slcan_tty_baudrate,
        config.candump_log_path if config.candump_log_path is not None else "disabled",
    )

    if args.mode == "send":
        run_sender(config)
    elif args.mode == "recv":
        run_controller(config)
    else:
        run_local_demo(config)
