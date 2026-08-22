"""Tests for the MCP server module."""

from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp import FastMCP

import mcp_venus_os.server as server
from mcp_venus_os.dbus_client import BatteryData, GridData, InverterData, PVData


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
    with patch("mcp_venus_os.server.get_dbus_client", return_value=client):
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
    with patch("mcp_venus_os.server.get_dbus_client", return_value=client):
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
    with patch("mcp_venus_os.server.get_dbus_client", return_value=client):
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
    with patch("mcp_venus_os.server.get_dbus_client", return_value=client):
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
    with patch("mcp_venus_os.server.get_dbus_client", return_value=client):
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
