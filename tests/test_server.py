"""Tests for the MCP server module."""

import json
import time
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp import FastMCP

import mcp_venus_os.server as server
from mcp_venus_os.dbus_client import BatteryData, GridData, InverterData, PVData
from mcp_venus_os.mqtt_client import MQTTClient


def test_get_dbus_client_creates_and_caches() -> None:
    with patch.object(server, "_dbus_client", None), patch.object(server, "DBusClient") as mock_cls:
        first = server.get_dbus_client()
        second = server.get_dbus_client()
    assert first is mock_cls.return_value
    assert second is first
    mock_cls.assert_called_once()


def test_get_mqtt_client_creates_and_caches() -> None:
    with patch.object(server, "_mqtt_client", None), patch.object(server, "MQTTClient") as mock_cls:
        first = server.get_mqtt_client()
        second = server.get_mqtt_client()
    assert first is mock_cls.return_value
    assert second is first
    mock_cls.assert_called_once()


def test_get_safety_validator_creates_and_caches() -> None:
    with (
        patch.object(server, "_safety_validator", None),
        patch.object(server, "SafetyValidator") as mock_cls,
    ):
        first = server.get_safety_validator()
        second = server.get_safety_validator()
    assert first is mock_cls.return_value
    assert second is first
    mock_cls.assert_called_once()


def test_get_confirmation_manager_creates_and_caches() -> None:
    with (
        patch.object(server, "_confirmation_manager", None),
        patch.object(server, "ConfirmationManager") as mock_cls,
    ):
        first = server.get_confirmation_manager()
        second = server.get_confirmation_manager()
    assert first is mock_cls.return_value
    assert second is first
    mock_cls.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_with_clients() -> None:
    dbus_client = AsyncMock()
    mqtt_client = AsyncMock()
    app = cast(FastMCP, Mock())
    with (
        patch.object(server, "_dbus_client", dbus_client),
        patch.object(server, "_mqtt_client", mqtt_client),
    ):
        async with server.lifespan(app):
            pass
    dbus_client.disconnect.assert_awaited_once()
    mqtt_client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_without_clients() -> None:
    app = cast(FastMCP, Mock())
    with (
        patch.object(server, "_dbus_client", None),
        patch.object(server, "_mqtt_client", None),
    ):
        async with server.lifespan(app):
            pass


@pytest.mark.asyncio
async def test_get_battery_soc() -> None:
    client = Mock()
    client.get_battery_data = AsyncMock(
        return_value=BatteryData(50.0, 13.0, 5.0, 65.0, 20.0, "Discharging", 60)
    )
    with (
        patch("mcp_venus_os.server.get_config", return_value=_dbus_backend()),
        patch("mcp_venus_os.server.get_dbus_client", return_value=client),
    ):
        result = await server.get_battery_soc(instance=1)
    assert result["soc"] == 50.0
    assert result["voltage"] == 13.0
    assert result["current"] == 5.0
    assert result["power"] == 65.0
    assert result["temperature"] == 20.0
    assert result["status"] == "Discharging"
    assert result["time_to_go"] == 60
    assert result["instance"] == 1
    client.get_battery_data.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_get_pv_power() -> None:
    client = Mock()
    client.get_pv_data = AsyncMock(return_value=PVData(100.0, 50.0, 2.0, 10.0, 1000.0))
    with (
        patch("mcp_venus_os.server.get_config", return_value=_dbus_backend()),
        patch("mcp_venus_os.server.get_dbus_client", return_value=client),
    ):
        result = await server.get_pv_power(instance=0)
    assert result["power"] == 100.0
    assert result["voltage"] == 50.0
    assert result["current"] == 2.0
    assert result["yield_today"] == 10.0
    assert result["yield_total"] == 1000.0
    assert result["instance"] == 0
    client.get_pv_data.assert_awaited_once_with(0)


@pytest.mark.asyncio
async def test_get_grid_status() -> None:
    client = Mock()
    client.get_grid_data = AsyncMock(return_value=GridData(200.0, 230.0, 1.0, 50.0, "ok"))
    with (
        patch("mcp_venus_os.server.get_config", return_value=_dbus_backend()),
        patch("mcp_venus_os.server.get_dbus_client", return_value=client),
    ):
        result = await server.get_grid_status(instance=0)
    assert result["power"] == 200.0
    assert result["voltage"] == 230.0
    assert result["current"] == 1.0
    assert result["frequency"] == 50.0
    assert result["status"] == "ok"
    assert result["instance"] == 0
    client.get_grid_data.assert_awaited_once_with(0)


@pytest.mark.asyncio
async def test_get_inverter_status() -> None:
    client = Mock()
    client.get_inverter_data = AsyncMock(
        return_value=InverterData("on", "running", 500.0, 0.0, 600.0, 35.0)
    )
    with (
        patch("mcp_venus_os.server.get_config", return_value=_dbus_backend()),
        patch("mcp_venus_os.server.get_dbus_client", return_value=client),
    ):
        result = await server.get_inverter_status(instance=0)
    assert result["mode"] == "on"
    assert result["state"] == "running"
    assert result["ac_power_out"] == 500.0
    assert result["ac_power_in"] == 0.0
    assert result["dc_power"] == 600.0
    assert result["temperature"] == 35.0
    assert result["instance"] == 0
    client.get_inverter_data.assert_awaited_once_with(0)


@pytest.mark.asyncio
async def test_list_devices() -> None:
    client = Mock()
    devices = [{"service": "s", "device_type": "battery", "instance": 0}]
    client.list_devices = AsyncMock(return_value=devices)
    with (
        patch("mcp_venus_os.server.get_config", return_value=_dbus_backend()),
        patch("mcp_venus_os.server.get_dbus_client", return_value=client),
    ):
        result = await server.list_devices()
    assert result == devices
    client.list_devices.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_mqtt_connect_success() -> None:
    client = Mock()
    client.connect = AsyncMock()
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.mqtt_connect()
    assert result == {"success": True, "connected": True}


@pytest.mark.asyncio
async def test_mqtt_connect_error() -> None:
    client = Mock()
    client.connect = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.mqtt_connect()
    assert result == {"success": False, "error": "boom"}


@pytest.mark.asyncio
async def test_mqtt_disconnect() -> None:
    client = Mock()
    client.disconnect = AsyncMock()
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.mqtt_disconnect()
    assert result == {"success": True, "connected": False}


@pytest.mark.asyncio
async def test_mqtt_subscribe_unsupported() -> None:
    # mqtt_subscribe is a documented stub: it must report failure rather
    # than pretend a subscription was created (see server.mqtt_subscribe).
    result = await server.mqtt_subscribe("N/venus-os/+")
    assert result["success"] is False
    assert result["error"] == "unsupported"
    assert "not yet implemented" in result["message"]


# --- helpers / fixtures for transport-dispatch tests -----------------------


def _dbus_backend() -> Mock:
    cfg = Mock()
    cfg.transport_backend = "dbus"
    return cfg


def _feed(client: MQTTClient, topic: str, payload: bytes) -> None:
    import paho.mqtt.client as paho

    msg = paho.MQTTMessage()
    msg._topic = topic.encode()
    msg.payload = payload
    client._on_message(cast(paho.Client, Mock()), None, msg)


def _mqtt_read_client(
    entries: dict[str, object], stale_after_seconds: float = 60.0
) -> MQTTClient:
    """Real MQTTClient preloaded with cached telemetry, connect() mocked out."""
    from mcp_venus_os.config import MQTTConfig, ServerConfig
    from mcp_venus_os.mqtt_client import Payload

    def _noop(_payload: Payload) -> None:
        """Callback that does nothing."""

    cfg = ServerConfig(mqtt=MQTTConfig(host="localhost", portal_id="testportal"))
    with (
        patch.object(server, "_mqtt_client", None),
        patch("mcp_venus_os.mqtt_client.get_config", return_value=cfg),
    ):
        client = server.get_mqtt_client()
    for topic, value in entries.items():
        _feed(client, topic.replace("<portal>", "testportal"), json.dumps(value).encode())
    if stale_after_seconds != 60.0:
        client.config.stale_after_seconds = stale_after_seconds
    cast(Any, client).connect = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_get_battery_soc_mqtt_serves_cache() -> None:
    client = _mqtt_read_client({"N/<portal>/battery/256/Soc": 77})
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_battery_soc(instance=256)
    assert result["soc"] == 77
    assert result["stale"] is False
    assert result["age_seconds"] is not None


@pytest.mark.asyncio
async def test_get_battery_soc_mqtt_stale_flagged() -> None:
    client = _mqtt_read_client({"N/<portal>/battery/512/Soc": 55}, stale_after_seconds=1.0)
    topic = "N/testportal/battery/512/Soc"
    old_value, _old_age = client.read_path("battery", 512, "Soc") or (None, 0.0)
    client._cache[topic] = (old_value, time.monotonic() - 30.0)
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_battery_soc(instance=512)
    assert result["stale"] is True
    assert result["age_seconds"] >= 29.0


@pytest.mark.asyncio
async def test_get_pv_power_mqtt_computes_power_from_voltage_times_current() -> None:
    client = _mqtt_read_client(
        {"N/<portal>/solarcharger/0/Pv/V": 50.0, "N/<portal>/solarcharger/0/Pv/I": 2.0}
    )
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_pv_power(instance=0)
    assert result["power"] == 100.0
    assert result["voltage"] == 50.0
    assert result["current"] == 2.0


@pytest.mark.asyncio
async def test_get_grid_status_mqtt_reads_system_aggregates() -> None:
    client = _mqtt_read_client(
        {
            "N/<portal>/system/0/Ac/Grid/Power": -1200,
            "N/<portal>/system/0/Ac/Grid/L1/Voltage": 230.5,
        }
    )
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_grid_status(instance=0)
    assert result["power"] == -1200
    assert result["voltage"] == 230.5
    assert result["current"] is None
    assert result["stale"] is False


@pytest.mark.asyncio
async def test_list_devices_mqtt_from_cache() -> None:
    client = _mqtt_read_client(
        {
            "N/<portal>/battery/256/Dc/0/Power": 10,
            "N/<portal>/vebus/257/Mode": 1,
            "N/<portal>/system/0/Ac/Grid/Power": 5,
        }
    )
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.list_devices()
    assert result == [
        {"device_type": "battery", "instance": 256},
        {"device_type": "system", "instance": 0},
        {"device_type": "vebus", "instance": 257},
    ]


def test_collect_mqtt_all_missing_marks_stale() -> None:
    client = _mqtt_read_client({})
    out = server._collect_mqtt(client, {"soc": ["Soc"]}, "battery", 999)
    assert out["soc"] is None
    assert out["stale"] is True
    assert out["age_seconds"] is None
