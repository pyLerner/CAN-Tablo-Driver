"""Базовые проверки HTTP API без CAN."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api_app import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    mock_scheduler = MagicMock()
    mock_scheduler.stop = AsyncMock()
    with patch("api_app.DisplaySendScheduler", return_value=mock_scheduler):
        with TestClient(create_app(SRC / "config.toml")) as c:
            c._mock_scheduler = mock_scheduler  # type: ignore[attr-defined]
            yield c


def test_ping(client: TestClient) -> None:
    r = client.get("/api/ping")
    assert r.status_code == 200
    data = r.json()
    assert data["running"] == "OK"
    assert "timestamp-utc" in data
    assert "display-id" in data
    assert data["display-id"] == "front-display"


def test_values_update_accepted(client: TestClient) -> None:
    r = client.put(
        "/api/leddisplays/v1/values/update",
        json={"values": {"1": "567А"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    client._mock_scheduler.submit.assert_called_once_with({"1": "567А"})  # type: ignore[attr-defined]


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
