"""Базовые проверки HTTP API без CAN."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api_app import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SRC / "config.toml"))


def test_ping(client: TestClient) -> None:
    r = client.get("/api/ping")
    assert r.status_code == 200
    data = r.json()
    assert data["running"] == "OK"
    assert "timestamp-utc" in data


def test_route_get_empty(client: TestClient) -> None:
    r = client.get("/api/leddisplays/v1/route/set")
    assert r.status_code == 200
    assert r.json()["first-string"] == ""


def test_led_config_merge() -> None:
    from led_config import deep_merge

    base = {"can": {"channel": "can0", "bitrate": 500000, "sender_tx_id": 1}}
    upd = {"can": {"bitrate": 250000}}
    m = deep_merge(base, upd)
    assert m["can"]["channel"] == "can0"
    assert m["can"]["bitrate"] == 250000
    assert m["can"]["sender_tx_id"] == 1
