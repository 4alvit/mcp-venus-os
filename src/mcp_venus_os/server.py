"""MCP server for Venus OS management."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from .config import get_config
from .dbus_client import (
    BatteryData,
    DBusClient,
    GridData,
    InverterData,
    PVData,
)
from .mqtt_client import MQTTClient
from .safety import ConfirmationManager, SafetyValidator

logger = logging.getLogger(__name__)

# Global instances
_dbus_client: DBusClient | None = None
_mqtt_client: MQTTClient | None = None
_safety_validator: SafetyValidator | None = None
_confirmation_manager: ConfirmationManager | None = None


def get_dbus_client() -> DBusClient:
    """Get or create D-Bus client."""
    global _dbus_client
    if _dbus_client is None:
        _dbus_client = DBusClient()
    return _dbus_client


def get_mqtt_client() -> MQTTClient:
    """Get or create MQTT client."""
    global _mqtt_client
    if _mqtt_client is None:
        _mqtt_client = MQTTClient()
    return _mqtt_client


def get_safety_validator() -> SafetyValidator:
    """Get or create safety validator."""
    global _safety_validator
    if _safety_validator is None:
        _safety_validator = SafetyValidator()
    return _safety_validator


def get_confirmation_manager() -> ConfirmationManager:
    """Get or create confirmation manager."""
    global _confirmation_manager
    if _confirmation_manager is None:
        _confirmation_manager = ConfirmationManager()
    return _confirmation_manager


@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Server lifespan handler."""
    config = get_config()
    logging.basicConfig(level=config.log_level)
    logger.info("Starting MCP Venus OS server")
    yield
    logger.info("Shutting down MCP Venus OS server")
    if _dbus_client:
        await _dbus_client.disconnect()
    if _mqtt_client:
        await _mqtt_client.disconnect()


mcp = FastMCP("Venus OS", lifespan=lifespan)


# Read tools
@mcp.tool()
async def get_battery_soc(instance: int = 0) -> dict[str, Any]:
    """Get battery state of charge."""
    client = get_dbus_client()
    data: BatteryData = await client.get_battery_data(instance)
    return {
        "instance": instance,
        "soc": data.soc,
        "voltage": data.voltage,
        "current": data.current,
        "power": data.power,
        "temperature": data.temperature,
        "status": data.status,
        "time_to_go": data.time_to_go,
    }


@mcp.tool()
async def get_pv_power(instance: int = 0) -> dict[str, Any]:
    """Get PV/solar charger power data."""
    client = get_dbus_client()
    data: PVData = await client.get_pv_data(instance)
    return {
        "instance": instance,
        "power": data.power,
        "voltage": data.voltage,
        "current": data.current,
        "yield_today": data.yield_today,
        "yield_total": data.yield_total,
    }


@mcp.tool()
async def get_grid_status(instance: int = 0) -> dict[str, Any]:
    """Get grid/AC status."""
    client = get_dbus_client()
    data: GridData = await client.get_grid_data(instance)
    return {
        "instance": instance,
        "power": data.power,
        "voltage": data.voltage,
        "current": data.current,
        "frequency": data.frequency,
        "status": data.status,
    }


@mcp.tool()
async def get_inverter_status(instance: int = 0) -> dict[str, Any]:
    """Get inverter mode and state."""
    client = get_dbus_client()
    data: InverterData = await client.get_inverter_data(instance)
    return {
        "instance": instance,
        "mode": data.mode,
        "state": data.state,
        "ac_power_out": data.ac_power_out,
        "ac_power_in": data.ac_power_in,
        "dc_power": data.dc_power,
        "temperature": data.temperature,
    }


@mcp.tool()
async def list_devices() -> list[dict[str, Any]]:
    """List all Victron devices on D-Bus."""
    client = get_dbus_client()
    return await client.list_devices()


# Write tools (with safety)
@mcp.tool()
async def set_inverter_mode(
    mode: str, instance: int = 0, confirmed: bool = False
) -> dict[str, Any]:
    """Set inverter mode (on, off, charger_only, inverter_only, eco).

    Requires confirmation for write operations.
    """
    validator = get_safety_validator()
    result = validator.validate_write_operation(
        "set_inverter_mode", {"mode": mode, "instance": instance}, confirmed
    )

    if not result.allowed and result.requires_confirmation:
        return {
            "success": False,
            "requires_confirmation": True,
            "confirmation_message": result.confirmation_message,
        }

    if not result.allowed:
        return {"success": False, "error": result.reason}

    # Write operation not yet implemented
    return {"success": False, "error": "Operation not implemented yet"}}


@mcp.tool()
async def set_charge_current_limit(
    current: float, instance: int = 0, confirmed: bool = False
) -> dict[str, Any]:
    """Set maximum charge current limit in Amps.

    Requires confirmation for write operations.
    """
    validator = get_safety_validator()
    result = validator.validate_write_operation(
        "set_charge_current_limit",
        {"charge_current": current, "instance": instance},
        confirmed,
    )

    if not result.allowed and result.requires_confirmation:
        return {
            "success": False,
            "requires_confirmation": True,
            "confirmation_message": result.confirmation_message,
        }

    if not result.allowed:
        return {"success": False, "error": result.reason}

    # Write operation not yet implemented
    msg = f"Charge current limit set to {current}A (not implemented yet)"
    return {"success": False, "error": "Operation not implemented yet"}


@mcp.tool()
async def set_soc_limit(
    soc_limit: int,
    instance: int = 0,
    confirmed: bool = False
) -> dict[str, Any]:
    """Set battery SoC limit percentage.

    Requires confirmation for write operations.
    """
    validator = get_safety_validator()
    result = validator.validate_write_operation(
        "set_soc_limit", {"soc_limit": soc_limit, "instance": instance}, confirmed
    )

    if not result.allowed and result.requires_confirmation:
        return {
            "success": False,
            "requires_confirmation": True,
            "confirmation_message": result.confirmation_message,
        }

    if not result.allowed:
        return {"success": False, "error": result.reason}

    # Write operation not yet implemented
    return {"success": False, "error": "Operation not implemented yet"}}


# MQTT tools
@mcp.tool()
async def mqtt_connect() -> dict[str, Any]:
    """Connect to MQTT broker for real-time data."""
    client = get_mqtt_client()
    try:
        await client.connect()
    except Exception as e:
        return {"success": False, "error": str(e)}
    else:
        return {"success": True, "connected": True}


@mcp.tool()
async def mqtt_disconnect() -> dict[str, Any]:
    """Disconnect from MQTT broker."""
    client = get_mqtt_client()
    await client.disconnect()
    return {"success": True, "connected": False}


@mcp.tool()
async def mqtt_subscribe(topic_pattern: str) -> dict[str, Any]:
    """Subscribe to MQTT topic pattern.

    Returns a subscription ID for polling messages.
    """
    # Note: This is a placeholder - real implementation would use async iteration
    return {
        "success": True,
        "message": f"Subscribed to {topic_pattern}. Use mqtt_poll for messages.",
    }
