"""Базовые проверки HTTP API без CAN."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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
    assert "display-id" in data
    assert data["display-id"] == "front-display"


@patch("api_app.send_display_values")
def test_values_update_accepted(_mock_send: object, client: TestClient) -> None:
    r = client.put(
        "/api/leddisplays/v1/values/update",
        json={"values": {"1": "567А"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"


def test_config_set_noop_empty_body(client: TestClient) -> None:
    r = client.post("/api/leddisplays/v1/config/set", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "noop"


def test_config_set_body_maps_animate_debug() -> None:
    from api_app import ConfigSetBody, _config_set_body_to_toml_updates

    body = ConfigSetBody(animate=False, debug=True)
    upd = _config_set_body_to_toml_updates(body)
    assert upd["display"]["animate"] is False
    assert upd["display"]["debug"] is True


def test_led_config_merge() -> None:
    from led_config import deep_merge

    base = {"can": {"channel": "can0", "bitrate": 500000}}
    upd = {"can": {"bitrate": 250000}}
    m = deep_merge(base, upd)
    assert m["can"]["channel"] == "can0"
    assert m["can"]["bitrate"] == 250000
