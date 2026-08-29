"""Tests for the D-Bus client."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from dbus_fast import BusType, MessageType

from mcp_venus_os.dbus_client import (
    BatteryData,
    DBusCallError,
    DBusClient,
    GridData,
    InverterData,
    NotConnectedError,
    PVData,
)


class FakeReply:
    def __init__(self, body: list[object], error: bool = False) -> None:
        self.body = body
        self.message_type = MessageType.ERROR if error else MessageType.METHOD_RETURN


class FakeMessage:
    def __init__(
        self,
        *,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: list[object] | None = None,
    ) -> None:
        self.destination = destination
        self.path = path
        self.interface = interface
        self.member = member
        self.signature = signature
        self.body = body if body is not None else []


class FakeBus:
    def __init__(
        self, values: dict[str, object] | None = None, names: list[str] | None = None
    ) -> None:
        self.values = values or {}
        self.names = names
        self.calls: list[FakeMessage] = []

    async def connect(self) -> FakeBus:
        return self

    async def call(self, msg: FakeMessage) -> FakeReply:
        self.calls.append(msg)
        if msg.member == "ListNames":
            if self.names is None:
                return FakeReply([], error=True)
            return FakeReply([self.names])
        prop = msg.body[1]
        if prop in self.values:
            return FakeReply([[prop, self.values[prop]]])
        return FakeReply([], error=True)


@contextmanager
def _patched_dbus(fake: FakeBus) -> Iterator[None]:
    """Patch the D-Bus message layer so no real bus is contacted."""
    with (
        patch("mcp_venus_os.dbus_client.Message", side_effect=FakeMessage),
        patch("mcp_venus_os.dbus_client.MessageBus", return_value=fake),
    ):
        yield


def test_service_path() -> None:
    client = DBusClient()
    service, path = client._service_path(5, "battery")
    assert service == "com.victronenergy.battery.5"
    assert path == "/Battery"


@pytest.mark.asyncio
async def test_connect_system_bus_and_disconnect() -> None:
    client = DBusClient()
    with patch("mcp_venus_os.dbus_client.MessageBus") as mock_bus:
        mock_bus.return_value.connect = AsyncMock(return_value=mock_bus.return_value)
        await client.connect()
        await client.connect()
        mock_bus.assert_called_once_with(bus_type=BusType.SYSTEM)
        await client.disconnect()
        mock_bus.return_value.disconnect.assert_called_once()
        await client.disconnect()
    assert not client._connected


@pytest.mark.asyncio
async def test_connect_session_bus() -> None:
    with (
        patch("mcp_venus_os.dbus_client.get_config") as mock_config,
        patch("mcp_venus_os.dbus_client.MessageBus") as mock_bus,
    ):
        mock_config.return_value.dbus.bus_type = "session"
        mock_bus.return_value.connect = AsyncMock(return_value=mock_bus.return_value)
        client = DBusClient()
        await client.connect()
    mock_bus.assert_called_once_with(bus_type=BusType.SESSION)


@pytest.mark.asyncio
async def test_get_property_value() -> None:
    client = DBusClient()
    fake = FakeBus({"Soc": 50})
    with _patched_dbus(fake):
        await client.connect()
        value = await client._get_property(
            "com.victronenergy.battery.0", "/Battery", "com.victronenergy.Battery", "Soc"
        )
    assert value == 50
    assert fake.calls[0].body == ["com.victronenergy.Battery", "Soc"]


@pytest.mark.asyncio
async def test_get_property_error() -> None:
    client = DBusClient()
    fake = FakeBus()
    with _patched_dbus(fake):
        await client.connect()
        with pytest.raises(DBusCallError):
            await client._get_property(
                "com.victronenergy.battery.0", "/Battery", "iface", "Missing"
            )


@pytest.mark.asyncio
async def test_get_property_not_connected() -> None:
    client = DBusClient()
    with pytest.raises(NotConnectedError):
        await client._get_property("com.victronenergy.battery.0", "/Battery", "iface", "Soc")


@pytest.mark.asyncio
async def test_get_battery_data() -> None:
    client = DBusClient()
    fake = FakeBus(
        {
            "Soc": 50,
            "Voltage": 13.0,
            "Current": 5.0,
            "Power": 65.0,
            "Temperature": 20.0,
            "Status": "Discharging",
            "TimeToGo": 60,
        }
    )
    with _patched_dbus(fake):
        data = await client.get_battery_data(instance=0)

    assert isinstance(data, BatteryData)
    assert data.soc == 50.0
    assert data.voltage == 13.0
    assert data.current == 5.0
    assert data.power == 65.0
    assert data.temperature == 20.0
    assert data.status == "Discharging"
    assert data.time_to_go == 60


@pytest.mark.asyncio
async def test_get_battery_data_no_time_to_go() -> None:
    client = DBusClient()
    fake = FakeBus(
        {
            "Soc": 50,
            "Voltage": 13.0,
            "Current": 5.0,
            "Power": 65.0,
            "Temperature": 20.0,
            "Status": "Discharging",
            "TimeToGo": 0,
        }
    )
    with _patched_dbus(fake):
        data = await client.get_battery_data(instance=0)
    assert data.time_to_go is None


@pytest.mark.asyncio
async def test_get_battery_data_error() -> None:
    client = DBusClient()
    fake = FakeBus({"Soc": 50})
    with _patched_dbus(fake), pytest.raises(DBusCallError):
        await client.get_battery_data(instance=0)


@pytest.mark.asyncio
async def test_get_pv_data() -> None:
    client = DBusClient()
    fake = FakeBus(
        {
            "PvPower": 100.0,
            "PvVoltage": 50.0,
            "PvCurrent": 2.0,
            "YieldToday": 10.0,
            "YieldTotal": 1000.0,
        }
    )
    with _patched_dbus(fake):
        data = await client.get_pv_data(instance=1)

    assert isinstance(data, PVData)
    assert data.power == 100.0
    assert data.voltage == 50.0
    assert data.current == 2.0
    assert data.yield_today == 10.0
    assert data.yield_total == 1000.0


@pytest.mark.asyncio
async def test_get_grid_data() -> None:
    client = DBusClient()
    fake = FakeBus(
        {
            "AcPowerOut": 200.0,
            "AcVoltageOut": 230.0,
            "AcCurrentOut": 1.0,
            "AcFrequencyOut": 50.0,
            "AcActiveInState": "ok",
        }
    )
    with _patched_dbus(fake):
        data = await client.get_grid_data(instance=0)

    assert isinstance(data, GridData)
    assert data.power == 200.0
    assert data.voltage == 230.0
    assert data.current == 1.0
    assert data.frequency == 50.0
    assert data.status == "ok"


@pytest.mark.asyncio
async def test_get_inverter_data() -> None:
    client = DBusClient()
    fake = FakeBus(
        {
            "Mode": "on",
            "State": "running",
            "AcPowerOut": 500.0,
            "AcPowerIn": 0.0,
            "DcPower": 600.0,
            "Temperature": 35.0,
        }
    )
    with _patched_dbus(fake):
        data = await client.get_inverter_data(instance=0)

    assert isinstance(data, InverterData)
    assert data.mode == "on"
    assert data.state == "running"
    assert data.ac_power_out == 500.0
    assert data.ac_power_in == 0.0
    assert data.dc_power == 600.0
    assert data.temperature == 35.0


@pytest.mark.asyncio
@pytest.mark.parametrize("getter", ["get_pv_data", "get_grid_data", "get_inverter_data"])
async def test_data_getters_error(getter: str) -> None:
    client = DBusClient()
    fake = FakeBus()
    with _patched_dbus(fake), pytest.raises(DBusCallError):
        await getattr(client, getter)(instance=0)


@pytest.mark.asyncio
async def test_list_devices() -> None:
    client = DBusClient()
    fake = FakeBus(
        names=["com.victronenergy.battery.0", "com.victronenergy.vebus.0", "com.victronenergy"]
    )
    with _patched_dbus(fake):
        devices = await client.list_devices()
    assert devices == [
        {"service": "com.victronenergy.battery.0", "device_type": "battery", "instance": 0},
        {"service": "com.victronenergy.vebus.0", "device_type": "vebus", "instance": 0},
    ]


@pytest.mark.asyncio
async def test_list_devices_error() -> None:
    client = DBusClient()
    fake = FakeBus()
    with _patched_dbus(fake), pytest.raises(DBusCallError):
        await client.list_devices()


@pytest.mark.asyncio
async def test_list_devices_skips_non_numeric_instance() -> None:
    client = DBusClient()
    fake = FakeBus(
        names=["com.victronenergy.ev22", "com.victronenergy.battery.0", "com.victronenergy"]
    )
    with _patched_dbus(fake):
        devices = await client.list_devices()
    assert devices == [
        {"service": "com.victronenergy.battery.0", "device_type": "battery", "instance": 0},
    ]


@pytest.mark.asyncio
async def test_list_devices_not_connected() -> None:
    client = DBusClient()
    with patch("mcp_venus_os.dbus_client.MessageBus") as mock_bus:
        mock_bus.return_value.connect = AsyncMock(return_value=None)
        with pytest.raises(NotConnectedError):
            await client.list_devices()
