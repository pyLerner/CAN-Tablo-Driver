"""
Имитация отправки на все табло из config.toml без CAN: те же табло и payload,
итоговые картинки — склейка областей в RGB и сохранение в каталог logs.

Запуск из корня проекта:
  uv run python src/simulate_all_displays.py --config src/config.toml
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from PIL import Image

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from led_config import MultiLedConfig, load_multi_led_config
from led_service import (
    _make_route_like_tablo,
    _rear_tablo,
    _ticker_tablo,
    route_json_internal,
    ticker_json_internal,
)
from main import RectMaskPacket, TextRenderer

LOGGER = logging.getLogger("simulate-displays")


class _CaptureTransport:
    """Накапливает ISO-TP payload байты (как BoundMultiIsoTp.send)."""

    def __init__(self, bucket: list[bytes]) -> None:
        self._bucket = bucket

    def send(self, payload: bytes) -> None:
        self._bucket.append(payload)


def _payloads_to_canvas(width: int, height: int, payloads: list[bytes]) -> Image.Image:
    """Склеивает области в одно изображение размера табло (как видит контроллер после отрисовки зон)."""
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    for raw in payloads:
        packet = RectMaskPacket.from_payload(raw)
        region = packet.to_image()
        canvas.paste(region, (packet.x, packet.y))
    return canvas


def _safe_name(prefix: str, suffix: str = ".png") -> str:
    return f"{prefix}{suffix}"


def simulate_all_to_logs(
    cfg: MultiLedConfig,
    route_json: str,
    ticker_json: Optional[str],
    output_dir: Path,
) -> list[Path]:
    """
    Формирует payload для каждого табло из конфига и сохраняет итоговые PNG в output_dir.

    Returns:
        Список путей к сохранённым файлам.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    renderer = TextRenderer(str(cfg.font_path))
    color = cfg.display_color_code
    saved: list[Path] = []

    def run_route_like(name: str, sec) -> None:
        if sec is None:
            return
        bucket: list[bytes] = []
        transport = _CaptureTransport(bucket)
        tablo = _make_route_like_tablo(sec, renderer, transport, color)
        tablo.send_to_tablo(route_json)
        if not bucket:
            LOGGER.warning("Нет payload для %s", name)
            return
        img = _payloads_to_canvas(sec.width, sec.height, bucket)
        path = output_dir / _safe_name(f"sim_{name}")
        img.save(path)
        saved.append(path)
        LOGGER.info("Сохранено: %s (%d областей)", path, len(bucket))

    run_route_like("front-display", cfg.front)
    run_route_like("side-front-display", cfg.side_front)
    run_route_like("side-rear-display", cfg.side_rear)

    if cfg.rear is not None:
        bucket: list[bytes] = []
        transport = _CaptureTransport(bucket)
        tablo = _rear_tablo(cfg.rear, renderer, transport, color)
        tablo.send_to_tablo(route_json)
        if bucket:
            img = _payloads_to_canvas(cfg.rear.width, cfg.rear.height, bucket)
            path = output_dir / _safe_name("sim_rear-display")
            img.save(path)
            saved.append(path)
            LOGGER.info("Сохранено: %s (%d областей)", path, len(bucket))
        else:
            LOGGER.warning("Нет payload для rear-display")

    if ticker_json is not None and cfg.tickers:
        for i, t in enumerate(cfg.tickers):
            bucket = []
            transport = _CaptureTransport(bucket)
            tablo = _ticker_tablo(t, renderer, transport, color)
            tablo.send_to_tablo(ticker_json)
            if not bucket:
                LOGGER.warning("Нет payload для ticker-board #%d", i + 1)
                continue
            img = _payloads_to_canvas(t.width, t.height, bucket)
            tag = f"{t.sender_tx_id:#x}"
            path = output_dir / _safe_name(f"sim_ticker-board_{tag}")
            img.save(path)
            saved.append(path)
            LOGGER.info("Сохранено: %s (%d областей)", path, len(bucket))

    return saved


def _load_route_json(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    data = json.loads(content)
    return json.dumps(
        {
            "firstString": data.get("firstString", ""),
            "secondString": data.get("secondString", ""),
            "thirdString": data.get("thirdString", ""),
        },
        ensure_ascii=False,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Имитация отправки на все табло: PNG в каталоге logs (из конфига).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_SCRIPT_DIR / "config.toml",
        help="Путь к config.toml (по умолчанию: src/config.toml рядом со скриптом).",
    )
    parser.add_argument(
        "--route-file",
        type=Path,
        default=None,
        help="JSON с firstString/secondString/thirdString (по умолчанию — TextIn.path из конфига).",
    )
    parser.add_argument(
        "--ticker-first",
        type=str,
        default="Строка тикера 1",
        help="Первая строка тикера (если задана --skip-ticker — не используется).",
    )
    parser.add_argument(
        "--ticker-second",
        type=str,
        default="Строка тикера 2",
        help="Вторая строка тикера.",
    )
    parser.add_argument(
        "--skip-ticker",
        action="store_true",
        help="Не симулировать ticker-board.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Куда сохранить PNG (по умолчанию — [logs].dir из конфига).",
    )
    args = parser.parse_args()

    cfg = load_multi_led_config(args.config.resolve())
    route_path = args.route_file if args.route_file is not None else cfg.text_in_path
    if not route_path.is_file():
        LOGGER.error("Файл маршрута не найден: %s", route_path)
        sys.exit(1)

    route_json = _load_route_json(route_path)
    ticker_json: Optional[str] = None
    if not args.skip_ticker and cfg.tickers:
        ticker_json = ticker_json_internal(args.ticker_first, args.ticker_second)

    out: Path = args.output_dir if args.output_dir is not None else cfg.logs_dir
    out = out.resolve()

    LOGGER.info("Конфиг: %s", args.config)
    LOGGER.info("Каталог вывода: %s", out)

    saved = simulate_all_to_logs(cfg, route_json, ticker_json, out)
    if not saved:
        LOGGER.warning("Ни одного изображения не сохранено (проверьте секции в конфиге).")
        sys.exit(2)
    LOGGER.info("Готово, файлов: %d", len(saved))


if __name__ == "__main__":
    main()
