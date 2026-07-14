"""Приоритет [logs].loglevel и legacy display.debug."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from led_config import (  # noqa: E402
    load_multi_led_config,
    resolve_log_level,
)


_MIN_DISPLAY = """
[display]
display-id = "t"
sender_tx_id = 1
sender_rx_id = 2
width = 64
height = 32
"""


def test_resolve_log_level_explicit() -> None:
    assert resolve_log_level("WARNING") == "WARNING"
    assert resolve_log_level("debug") == "DEBUG"


def test_resolve_log_level_from_debug_alias() -> None:
    assert resolve_log_level(None, debug=True, debug_key_present=True) == "DEBUG"
    assert resolve_log_level(None, debug=False, debug_key_present=True) == "INFO"


def test_resolve_log_level_default_info() -> None:
    assert resolve_log_level(None) == "INFO"


def test_resolve_log_level_explicit_wins_over_debug() -> None:
    assert (
        resolve_log_level("WARNING", debug=True, debug_key_present=True) == "WARNING"
    )


def test_load_config_loglevel_explicit(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text(
        f"""
[logs]
loglevel = "WARNING"
{_MIN_DISPLAY}
""",
        encoding="utf-8",
    )
    cfg = load_multi_led_config(path)
    assert cfg.log_level == "WARNING"
    assert cfg.animate is True


def test_load_config_debug_true_without_loglevel(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text(
        f"""
{_MIN_DISPLAY}
debug = true
""",
        encoding="utf-8",
    )
    cfg = load_multi_led_config(path)
    assert cfg.debug is True
    assert cfg.log_level == "DEBUG"


def test_load_config_both_loglevel_wins(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text(
        f"""
[logs]
loglevel = "INFO"
{_MIN_DISPLAY}
debug = true
animate = true
""",
        encoding="utf-8",
    )
    cfg = load_multi_led_config(path)
    assert cfg.debug is True
    assert cfg.log_level == "INFO"
