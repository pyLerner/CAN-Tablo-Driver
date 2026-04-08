"""
Имитация отправки на одно табло из config.toml без CAN: склейка областей в PNG.

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

from led_config import load_multi_led_config
from led_service import values_json
from main import RectMaskPacket, TextRenderer, ZonedDisplayTablo

LOGGER = logging.getLogger("simulate-displays")


class _CaptureTransport:
    def __init__(self, bucket: list[bytes]) -> None:
        self._bucket = bucket

    def send(self, payload: bytes) -> None:
        self._bucket.append(payload)


def _payloads_to_canvas(width: int, height: int, payloads: list[bytes]) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    for raw in payloads:
        packet = RectMaskPacket.from_payload(raw)
        region = packet.to_image()
        canvas.paste(region, (packet.x, packet.y))
    return canvas


def simulate_display_to_png(
    cfg,
    values: dict[str, str],
    output_dir: Path,
) -> Optional[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bucket: list[bytes] = []
    transport = _CaptureTransport(bucket)
    renderer = TextRenderer(str(cfg.font_path))
    tablo = ZonedDisplayTablo(cfg, renderer, transport)
    tablo.send_to_tablo(values_json(values))
    if not bucket:
        LOGGER.warning("Нет payload для табло")
        return None
    img = _payloads_to_canvas(cfg.display_width, cfg.display_height, bucket)
    path = output_dir / "sim_display.png"
    img.save(path)
    LOGGER.info("Сохранено: %s (%d областей)", path, len(bucket))
    return path


def _load_values_from_file(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    v = data.get("values", data)
    if not isinstance(v, dict):
        return {}
    return {str(k): str(val) for k, val in v.items()}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Имитация одного табло: PNG в каталоге логов.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_SCRIPT_DIR / "config.toml",
        help="Путь к config.toml.",
    )
    parser.add_argument(
        "--values-file",
        type=Path,
        default=None,
        help="JSON с полем values (по умолчанию — TextIn.path из конфига).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Куда сохранить PNG (по умолчанию — [logs].dir из конфига).",
    )
    args = parser.parse_args()

    cfg = load_multi_led_config(args.config.resolve())
    vf = args.values_file if args.values_file is not None else cfg.text_in_path
    if not vf.is_file():
        LOGGER.error("Файл не найден: %s", vf)
        sys.exit(1)

    values = _load_values_from_file(vf)
    out = (args.output_dir if args.output_dir is not None else cfg.logs_dir).resolve()

    LOGGER.info("Конфиг: %s", args.config)
    LOGGER.info("Вывод: %s", out)

    path = simulate_display_to_png(cfg, values, out)
    if path is None:
        LOGGER.warning("Изображение не сохранено (нет зон или пустой вывод).")
        sys.exit(2)


if __name__ == "__main__":
    main()
