#!/usr/bin/env python3
"""Запуск HTTP API (FastAPI + uvicorn). Параметры host и port — из секции [api-server] в config.toml."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Репозиторий: рядом с run_api_server.py лежит каталог src/.
# Установка через wheel: модуль в site-packages — корень приложения задаётся CAN_TABLO_HOME (в Docker: /opt/can-tablo).
_here = Path(__file__).resolve().parent
if (_here / "src").is_dir():
    _ROOT = _here
else:
    _ROOT = Path(os.environ.get("CAN_TABLO_HOME", "/opt/can-tablo")).resolve()
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LED tablo HTTP API (хост и порт из [api-server] в config.toml)",
    )
    parser.add_argument(
        "--config",
        default="./config.toml",
        help="Путь к config.toml (по умолчанию ./config.toml)",
    )
    args = parser.parse_args()
    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()
    else:
        config_path = config_path.resolve()

    from led_config import load_multi_led_config
    from main import LOGGER, run_api_server, setup_logging

    cfg = load_multi_led_config(config_path)
    setup_logging(
        log_dir=cfg.logs_dir,
        filename=cfg.log_filename,
        max_bytes=cfg.log_max_bytes,
        backup_count=cfg.log_backup_count,
    )
    LOGGER.info(
        "Запуск HTTP API, config=%s host=%s port=%s",
        config_path,
        cfg.api_server_host,
        cfg.api_server_port,
    )
    run_api_server(cfg)


if __name__ == "__main__":
    main()
