"""D-Bus client for reading Venus OS data."""

import logging
from dataclasses import dataclass
from typing import Any

from dbus_fast import BusType, Message
from dbus_fast.aio import MessageBus

from .config import get_config

logger = logging.getLogger(__name__)


class DBusError(Exception):
    """Base exception for D-Bus errors."""

    pass


class NotConnectedError(DBusError):
    """Raised when D-Bus is not connected."""

    pass


class DBusCallError(DBusError):
    """Raised when a D-Bus call fails."""

    pass


@dataclass
class BatteryData:
    """Battery data from Venus OS."""
    soc: float
    voltage: float
    current: float
    power: float
    temperature: float
    status: str
    time_to_go: int | None = None


@dataclass
class PVData:
    """PV/Solar data from Venus OS."""
    power: float
    voltage: float
    current: float
    yield_today: float
    yield_total: float


@dataclass
class GridData:
    """Grid/AC data from Venus OS."""
    power: float
    voltage: float
    current: float
    frequency: float
    status: str


@dataclass
class InverterData:
    """Inverter data from Venus OS."""
    mode: str
    state: str
    ac_power_out: float
    ac_power_in: float
    dc_power: float
    temperature: float


class DBusClient:
    """D-Bus client for Victron Venus OS."""

    def __init__(self) -> None:
        self.config = get_config().dbus
        self.bus: MessageBus | None = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to D-Bus."""
        if self._connected:
            return

        bus_type = BusType.SYSTEM if self.config.bus_type == "system" else BusType.SESSION
        self.bus = await MessageBus(bus_type=bus_type).connect()
        self._connected = True
        logger.info("Connected to D-Bus (%s)", self.config.bus_type)

    async def disconnect(self) -> None:
        """Disconnect from D-Bus."""
        if self.bus and self._connected:
            self.bus.disconnect()
            self._connected = False
            logger.info("Disconnected from D-Bus")

    def _service_path(self, device_instance: int, device_type: str) -> tuple[str, str]:
        """Get service name and object path for a device."""
        service = f"{self.config.service_name}.{device_type}.{device_instance}"
        path = f"/{device_type.capitalize()}"
        return service, path

    async def _get_property(
        self, service: str, path: str, interface: str, property_name: str
    ) -> Any:  # noqa: ANN401
        """Get a D-Bus property value."""
        if not self.bus:
            raise NotConnectedError()

        msg = Message(
            destination=service,
            path=path,
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=[interface, property_name],
        )
        reply = await self.bus.call(msg)
        if reply.message_type == Message.MessageType.ERROR:
            raise DBusCallError(reply.body)
        return reply.body[0][1]

    async def get_battery_data(self, instance: int = 0) -> BatteryData:
        """Get battery data from Venus OS."""
        await self.connect()
        service, path = self._service_path(instance, "battery")

        try:
            soc = await self._get_property(
                service, path, "com.victronenergy.Battery", "Soc"
            )
            voltage = await self._get_property(
                service, path, "com.victronenergy.Battery", "Voltage"
            )
            current = await self._get_property(
                service, path, "com.victronenergy.Battery", "Current"
            )
            power = await self._get_property(
                service, path, "com.victronenergy.Battery", "Power"
            )
            temperature = await self._get_property(
                service, path, "com.victronenergy.Battery", "Temperature"
            )
            status = await self._get_property(
                service, path, "com.victronenergy.Battery", "Status"
            )
            time_to_go = await self._get_property(
                service, path, "com.victronenergy.Battery", "TimeToGo"
            )

            return BatteryData(
                soc=float(soc),
                voltage=float(voltage),
                current=float(current),
                power=float(power),
                temperature=float(temperature),
                status=str(status),
                time_to_go=int(time_to_go) if time_to_go else None,
            )
        except Exception:
            logger.exception("Failed to get battery data")
            raise

    async def get_pv_data(self, instance: int = 0) -> PVData:
        """Get PV/Solar data from Venus OS."""
        await self.connect()
        service, path = self._service_path(instance, "solarcharger")

        try:
            power = await self._get_property(
                service, path, "com.victronenergy.Solarcharger", "PvPower"
            )
            voltage = await self._get_property(
                service, path, "com.victronenergy.Solarcharger", "PvVoltage"
            )
            current = await self._get_property(
                service, path, "com.victronenergy.Solarcharger", "PvCurrent"
            )
            yield_today = await self._get_property(
                service, path, "com.victronenergy.Solarcharger", "YieldToday"
            )
            yield_total = await self._get_property(
                service, path, "com.victronenergy.Solarcharger", "YieldTotal"
            )

            return PVData(
                power=float(power),
                voltage=float(voltage),
                current=float(current),
                yield_today=float(yield_today),
                yield_total=float(yield_total),
            )
        except Exception:
            logger.exception("Failed to get PV data")
            raise

    async def get_grid_data(self, instance: int = 0) -> GridData:
        """Get grid/AC data from Venus OS."""
        await self.connect()
        service, path = self._service_path(instance, "vebus")

        try:
            power = await self._get_property(
                service, path, "com.victronenergy.Vebus", "AcPowerOut"
            )
            voltage = await self._get_property(
                service, path, "com.victronenergy.Vebus", "AcVoltageOut"
            )
            current = await self._get_property(
                service, path, "com.victronenergy.Vebus", "AcCurrentOut"
            )
            frequency = await self._get_property(
                service, path, "com.victronenergy.Vebus", "AcFrequencyOut"
            )
            status = await self._get_property(
                service, path, "com.victronenergy.Vebus", "AcActiveInState"
            )

            return GridData(
                power=float(power),
                voltage=float(voltage),
                current=float(current),
                frequency=float(frequency),
                status=str(status),
            )
        except Exception:
            logger.exception("Failed to get grid data")
            raise

    async def get_inverter_data(self, instance: int = 0) -> InverterData:
        """Get inverter data from Venus OS."""
        await self.connect()
        service, path = self._service_path(instance, "vebus")

        try:
            mode = await self._get_property(
                service, path, "com.victronenergy.Vebus", "Mode"
            )
            state = await self._get_property(
                service, path, "com.victronenergy.Vebus", "State"
            )
            ac_power_out = await self._get_property(
                service, path, "com.victronenergy.Vebus", "AcPowerOut"
            )
            ac_power_in = await self._get_property(
                service, path, "com.victronenergy.Vebus", "AcPowerIn"
            )
            dc_power = await self._get_property(
                service, path, "com.victronenergy.Vebus", "DcPower"
            )
            temperature = await self._get_property(
                service, path, "com.victronenergy.Vebus", "Temperature"
            )

            return InverterData(
                mode=str(mode),
                state=str(state),
                ac_power_out=float(ac_power_out),
                ac_power_in=float(ac_power_in),
                dc_power=float(dc_power),
                temperature=float(temperature),
            )
        except Exception:
            logger.exception("Failed to get inverter data")
            raise

    async def list_devices(self) -> list[dict[str, Any]]:
        """List all Victron devices on D-Bus."""
        await self.connect()
        if not self.bus:
            raise NotConnectedError()

        msg = Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="ListNames",
        )
        reply = await self.bus.call(msg)
        if reply.message_type == Message.MessageType.ERROR:
            raise DBusCallError(reply.body)

        names = reply.body[0]
        victron_names = [
            n for n in names if n.startswith(self.config.service_name + ".")
        ]

        devices = []
        for name in victron_names:
            parts = name.split(".")
            if len(parts) >= 3:
                devices.append({
                    "service": name,
                    "device_type": parts[-2],
                    "instance": int(parts[-1]),
                })
        return devices
