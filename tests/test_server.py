"""Tests for the MCP server module."""

import asyncio
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
        patch.object(server, "_startup_warmup", new=AsyncMock()),
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
        patch.object(server, "_startup_warmup", new=AsyncMock()),
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
    client._drain_inbox()


def _mqtt_read_client(entries: dict[str, object], stale_after_seconds: float = 60.0) -> MQTTClient:
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
    # Fixture clients simulate post-warm-up state: marker already cached so
    # _mqtt_ready returns without waiting (see server.MQTT_WARMUP_TIMEOUT_S).
    _feed(client, "N/testportal/full_publish_completed", b'{"value":1}')
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
async def test_get_pv_power_mqtt_multi_instance_fans_out() -> None:
    """instance=0 returns every discovered solarcharger plus total power."""
    client = _mqtt_read_client(
        {
            "N/<portal>/solarcharger/292/Yield/Power": 35,
            "N/<portal>/solarcharger/290/Yield/Power": 25,
            "N/<portal>/solarcharger/291/Yield/Power": 33,
        }
    )
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_pv_power()
    assert [r["instance"] for r in result["readings"]] == [290, 291, 292]
    assert all(r["power"] is not None for r in result["readings"])
    assert result["total_power"] == 93.0


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
    readings = result["readings"]
    assert len(readings) == 1
    assert readings[0]["power"] == 100.0
    assert result["total_power"] == 100.0


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


@pytest.mark.asyncio
async def test_get_battery_soc_mqtt_auto_discovers_instance() -> None:
    """Default instance=0 fans out over discovered battery/<n> topics."""
    client = _mqtt_read_client(
        {
            "N/<portal>/battery/289/Soc": 44,
            "N/<portal>/battery/513/Soc": 46,
        }
    )
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_battery_soc(instance=0)
    assert [r["instance"] for r in result["readings"]] == [289, 513]
    assert sorted(r["soc"] for r in result["readings"]) == [44, 46]


@pytest.mark.asyncio
async def test_get_pv_power_mqtt_pvinverter_layout() -> None:
    """pvinverter services use Ac/* paths and are auto-discovered."""
    client = _mqtt_read_client(
        {
            "N/<portal>/pvinverter/369/Ac/Power": 1500,
            "N/<portal>/pvinverter/369/Ac/L1/Voltage": 230.0,
            "N/<portal>/pvinverter/369/Ac/L1/Current": 6.5,
            "N/<portal>/pvinverter/369/Ac/Energy/Daily": 3.2,
            "N/<portal>/pvinverter/369/Ac/Energy/Forward": 120.5,
        }
    )
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_pv_power(instance=369)
    assert result["instance"] == 369
    assert result["power"] == 1500
    assert result["voltage"] == 230.0
    assert result["yield_today"] == 3.2
    assert result["yield_total"] == 120.5


@pytest.mark.asyncio
async def test_get_grid_status_mqtt_grid_service_layout() -> None:
    """grid/<instance> meter service paths, not system/0 aggregates."""
    client = _mqtt_read_client(
        {
            "N/<portal>/grid/40/Ac/Power": -600,
            "N/<portal>/grid/40/Ac/L1/Voltage": 231.2,
            "N/<portal>/grid/40/Ac/Frequency": 49.98,
            "N/<portal>/grid/40/Connected": 1,
        }
    )
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_grid_status(instance=40)
    assert result["instance"] == 40
    assert result["power"] == -600
    assert result["voltage"] == 231.2
    assert result["frequency"] == 49.98


def test_discover_instance_missing_type_returns_none() -> None:
    client = _mqtt_read_client({"N/<portal>/battery/256/Soc": 77})
    assert client.discover_instance("vebus") is None
    assert client.discover_instance("battery") == 256


@pytest.mark.asyncio
async def test_mqtt_ready_waits_for_full_publish_marker() -> None:
    """Cold start blocks until the gateway full-publish marker lands."""
    client = _mqtt_read_client({})  # cold cache
    cast(Any, client).connect = AsyncMock()

    async def _fill_later() -> None:
        await asyncio.sleep(0.05)
        _feed(client, "N/testportal/full_publish_completed", b'{"value":1}')
        _feed(client, "N/testportal/vebus/257/Mode", b'{"value":1}')

    task = asyncio.create_task(_fill_later())
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        out = await server._mqtt_ready()
    await task
    assert any("/vebus/" in t for t in out._cache)


@pytest.mark.asyncio
async def test_mqtt_ready_times_out_without_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """No marker (old firmware) → proceed after the timeout instead of hanging."""
    monkeypatch.setattr(server, "MQTT_WARMUP_TIMEOUT_S", 0.1)
    client = _mqtt_read_client({"N/<portal>/battery/256/Soc": 50})
    # Drop the fixture's marker so the cold-start path actually runs.
    client._cache.pop("N/testportal/full_publish_completed", None)
    cast(Any, client).connect = AsyncMock()
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        out = await server._mqtt_ready()
    assert out.read_path("battery", 256, "Soc") is not None


# --- capability detection / conditional tools -------------------------------

from mcp_venus_os.capabilities import detect_capabilities  # noqa: E402


def test_detect_capabilities_markers() -> None:
    topics = [
        "N/testportal/battery/289/Soc",
        "inverter/state",
        "tank/21/Level",
        "tank/22/Level",
        "battery/sensor/current_total",  # dbus-mqtt-battery, no marker → ignored
        "tele/tasmota_120/SENSOR",
    ]
    assert detect_capabilities(topics) == {"control", "pump"}


def test_detect_capabilities_empty_without_companions() -> None:
    assert detect_capabilities(["N/x/system/0/Serial", "W/x/vebus/1/Mode"]) == set()


@pytest.mark.asyncio
async def test_apply_capability_tools_registers_once() -> None:
    client = _mqtt_read_client({"inverter/state": {"gt": -1}, "tank/21/Level": 44})
    with (
        patch.object(server, "_registered_capabilities", set()),
        patch.object(server.mcp, "add_tool") as mock_add,
    ):
        first = server._apply_capability_tools(client)
        second = server._apply_capability_tools(client)
    assert first == ["control", "pump"]
    assert second == []
    registered_names = [c.args[0].__name__ for c in mock_add.call_args_list]
    assert registered_names == ["get_control_state", "get_tank_level"]


@pytest.mark.asyncio
async def test_get_control_state_serves_cached_payload() -> None:
    state = {"gt": -537, "inverter_state": "Bulk", "batteries": [{"soc": 44.0}]}
    client = _mqtt_read_client({"inverter/state": state})
    cast(Any, client).connect = AsyncMock()
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_control_state()
    assert result["success"] is True
    assert result["state"]["inverter_state"] == "Bulk"
    assert result["stale"] is False


@pytest.mark.asyncio
async def test_get_tank_level_reads_cached_tanks() -> None:
    client = _mqtt_read_client({"tank/21/Level": 44, "tank/9/Level": 80})
    cast(Any, client).connect = AsyncMock()
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_tank_level()
    levels = sorted(r["level"] for r in result["readings"])
    assert levels == [44, 80]


@pytest.mark.asyncio
async def test_capabilities_resource_reflects_groups() -> None:
    with patch.object(server, "_registered_capabilities", {"control"}):
        text = server.capabilities_resource()
    assert "control" in text
    assert "instance=0" in text


def test_on_message_unwraps_gateway_value_wrapper() -> None:
    client = _mqtt_read_client({})
    _feed(client, "N/testportal/battery/256/Soc", b'{"value": 77}')
    cached = client.read_path("battery", 256, "Soc")
    assert cached is not None
    assert cached[0] == 77  # plain scalar, not {"value": 77}


@pytest.mark.asyncio
async def test_startup_warmup_failure_is_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> None:
        raise RuntimeError

    monkeypatch.setattr(server, "_startup_warmup", _boom)
    cfg = Mock()
    cfg.transport_backend = "mqtt"
    cfg.log_level = "INFO"
    app = cast(FastMCP, Mock())
    with (
        patch.object(server, "_dbus_client", None),
        patch.object(server, "_mqtt_client", None),
        patch("mcp_venus_os.server.get_config", return_value=cfg),
    ):
        async with server.lifespan(app):
            pass


@pytest.mark.asyncio
async def test_get_inverter_status_decodes_enums() -> None:
    """Raw vebus codes come back with mode_name/state_name alongside."""
    client = _mqtt_read_client({"N/<portal>/vebus/290/Mode": 3, "N/<portal>/vebus/290/State": 3})
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_inverter_status(instance=290)
    assert result["mode_name"] == "eco"
    assert result["state_name"] == "bulk"


@pytest.mark.asyncio
async def test_get_inverter_status_unknown_codes_fall_back() -> None:
    client = _mqtt_read_client({"N/<portal>/vebus/290/Mode": 7, "N/<portal>/vebus/290/State": 99})
    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await server.get_inverter_status(instance=290)
    assert result["mode_name"] == "code 7"
    assert result["state_name"] == "code 99"
