"""MCP server for Venus OS management."""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

from .config import get_config
from .dbus_client import (
    BatteryData,
    DBusClient,
    GridData,
    InverterData,
    PVData,
)
from .mqtt_client import MQTTClient, MQTTError, Payload
from .safety import ConfirmationManager, SafetyValidator

logger = logging.getLogger(__name__)

# Read-back window for W/… writes before reporting failure
WRITE_VERIFY_TIMEOUT_S = 5.0

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


def _http_auth() -> StaticTokenVerifier | None:
    """Static bearer-token verifier when SERVER_AUTH_TOKEN is set (HTTP mode only)."""
    cfg = get_config()
    if cfg.server_auth_token:
        return StaticTokenVerifier(tokens={cfg.server_auth_token: {"client_id": "claude-code"}})
    return None


mcp = FastMCP("Venus OS", lifespan=lifespan, auth=_http_auth())


def _use_mqtt() -> bool:
    """True unless the on-device D-Bus backend is explicitly selected."""
    return get_config().transport_backend != "dbus"


# Cold-start cap waiting for the gateway's initial full publish
MQTT_WARMUP_TIMEOUT_S = 20.0


async def _mqtt_ready() -> MQTTClient:
    """Get the MQTT client once the gateway finished its initial full publish.

    After a fresh connect the Venus MQTT gateway waits ~2-3s, then floods the
    entire item tree, ending with ``N/<portalId>/full_publish_completed``.
    Wait for that marker so instance auto-discovery sees the complete tree;
    proceed after the timeout on gateways that never send it.
    """
    client = get_mqtt_client()
    await client.connect()
    if client._cache:
        return client
    done_topic = f"{client.prefix}/full_publish_completed"
    deadline = time.monotonic() + MQTT_WARMUP_TIMEOUT_S
    while done_topic not in client._cache:
        if time.monotonic() > deadline:
            logger.warning(
                "MQTT full publish not seen within %.0fs (%d topics cached)",
                MQTT_WARMUP_TIMEOUT_S,
                len(client._cache),
            )
            break
        await asyncio.sleep(0.25)
    return client


# MQTT item paths per tool field; first available candidate wins. Paths follow
# the Venus OS MQTT gateway layout (verified against live gateway topics).
BATTERY_PATHS: dict[str, list[str]] = {
    "soc": ["Soc"],
    "voltage": ["Dc/0/Voltage", "Voltage"],
    "current": ["Dc/0/Current", "Current"],
    "power": ["Dc/0/Power", "Power"],
    "temperature": ["Dc/0/Temperature", "Temperature"],
    "status": ["Status"],
    "time_to_go": ["TimeToGo"],
}
PV_PATHS: dict[str, list[str]] = {  # pvinverter layout first, solarcharger second
    "power": ["Ac/Power", "Yield/Power"],
    "voltage": ["Ac/L1/Voltage", "Ac/L2/Voltage", "Ac/L3/Voltage", "Pv/V"],
    "current": ["Ac/L1/Current", "Ac/L2/Current", "Ac/L3/Current", "Pv/I"],
    "yield_today": ["Ac/Energy/Daily", "Yield/Today"],
    "yield_total": ["Ac/Energy/Forward", "Yield/Pv", "Yield/User"],
}
GRID_PATHS: dict[str, list[str]] = {  # grid meter service (grid/<instance>)
    "power": ["Ac/Power", "Ac/L1/Power", "Ac/L2/Power", "Ac/L3/Power"],
    "voltage": ["Ac/L1/Voltage", "Ac/L2/Voltage", "Ac/L3/Voltage"],
    "current": ["Ac/L1/Current", "Ac/L2/Current", "Ac/L3/Current"],
    "frequency": ["Ac/Frequency", "Ac/L1/Frequency"],
    "status": ["Connected"],
}
INVERTER_PATHS: dict[str, list[str]] = {
    "mode": ["Mode"],
    "state": ["State"],
    "ac_power_out": ["Ac/Out/P"],
    "ac_power_in": ["Ac/ActiveIn/P"],
    "dc_power": ["Dc/0/Power", "Dc/Pv/Power"],
    "temperature": ["Dc/0/Temperature", "Temperature"],
}


def _collect_mqtt(
    client: MQTTClient,
    field_paths: dict[str, list[str]],
    device_type: str,
    instance: int,
) -> dict[str, Any]:
    """Collect fields from the MQTT read cache with a stale-data guard."""
    stale_after = client.config.stale_after_seconds
    out: dict[str, Any] = {}
    max_age = 0.0
    seen_any = False
    for field, candidates in field_paths.items():
        result = client.read_first(device_type, instance, candidates)
        if result is None:
            out[field] = None
            continue
        value, age = result
        out[field] = value
        seen_any = True
        max_age = max(max_age, age)
    out["stale"] = bool(seen_any and max_age > stale_after) or not seen_any
    out["age_seconds"] = round(max_age, 1) if seen_any else None
    return out


def _resolve_mqtt_instance(
    client: MQTTClient, device_types: tuple[str, ...], instance: int
) -> tuple[str, int]:
    """Pick the service type/instance to read; auto-discover when instance <= 0.

    Venus services use nonzero device instances (e.g. battery/513, grid/40),
    so a default ``instance=0`` resolves against the discovered topic cache.
    """
    if instance > 0:
        return device_types[0], instance
    for device_type in device_types:
        found = client.discover_instance(device_type)
        if found is not None:
            return device_type, found
    return device_types[0], instance


async def _mqtt_write_and_verify(
    client: MQTTClient,
    device_type: str,
    instance: int,
    path: str,
    value: Payload,
) -> dict[str, Any]:
    """Publish a value to ``W/…`` and confirm it appears on the matching N topic."""
    item_topic = f"{client.write_prefix}/{device_type}/{instance}/{path}"
    try:
        client.publish(item_topic, value)
        client.start_keepalive(item_topic)
    except MQTTError as exc:
        return {"success": False, "error": f"publish failed: {exc}"}

    deadline = time.monotonic() + WRITE_VERIFY_TIMEOUT_S
    while time.monotonic() < deadline:
        result = client.read_first(device_type, instance, [path])
        if result is not None and _values_match(result[0], value):
            elapsed = round(WRITE_VERIFY_TIMEOUT_S - (deadline - time.monotonic()), 1)
            return {
                "success": True,
                "value": value,
                "topic": item_topic,
                "verified_after_s": elapsed,
            }
        await asyncio.sleep(0.2)
    return {
        "success": False,
        "error": (
            f"write published to {item_topic} but read-back on "
            f"N/{client.config.portal_id}/…/{path} did not reflect it within "
            f"{WRITE_VERIFY_TIMEOUT_S}s"
        ),
        "value": value,
        "topic": item_topic,
    }


def _values_match(received: Payload, expected: Payload) -> bool:
    """Compare a read-back value with the written one (numeric-tolerant)."""
    if received == expected:
        return True
    with contextlib.suppress(TypeError, ValueError):
        return float(received) == float(expected)  # type: ignore[arg-type]
    return False


def _mode_code(device_type: str, mode: str) -> int | None:
    """Map a safety-validated mode name to its device-type enum code.

    ponytail: per-device enums from Victron docs; verify against target
    firmware before trusting charger_only/inverter_only entries.
    """
    codes = MODE_CODES.get(device_type, {})
    code = codes.get(mode)
    return int(code) if code is not None else None


MODE_CODES: dict[str, dict[str, int]] = {
    # MultiPlus/Quattro vebus Mode enum
    "vebus": {"on": 1, "off": 4},
    # Phoenix-style inverter Mode enum
    "inverter": {"on": 1, "off": 2, "eco": 4},
    # Solar charger Mode enum
    "solarcharger": {"on": 1, "off": 4},
}


# Read tools
@mcp.tool()
async def get_battery_soc(instance: int = 0) -> dict[str, Any]:
    """Get battery state of charge."""
    if _use_mqtt():
        client = await _mqtt_ready()
        dtype, inst = _resolve_mqtt_instance(client, ("battery",), instance)
        return {"instance": inst} | _collect_mqtt(client, BATTERY_PATHS, dtype, inst)

    dbus_client = get_dbus_client()
    data: BatteryData = await dbus_client.get_battery_data(instance)
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
    if _use_mqtt():
        client = await _mqtt_ready()
        dtype, inst = _resolve_mqtt_instance(client, ("solarcharger", "pvinverter"), instance)
        out = {"instance": inst} | _collect_mqtt(client, PV_PATHS, dtype, inst)
        # Fall back to computed power from voltage × current when absent
        if out["power"] is None and out["voltage"] is not None and out["current"] is not None:
            with contextlib.suppress(TypeError, ValueError):
                out["power"] = round(float(out["voltage"]) * float(out["current"]), 1)
        return out

    dbus_client = get_dbus_client()
    data: PVData = await dbus_client.get_pv_data(instance)
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
    if _use_mqtt():
        client = await _mqtt_ready()
        dtype, inst = _resolve_mqtt_instance(client, ("grid",), instance)
        return {"instance": inst} | _collect_mqtt(client, GRID_PATHS, dtype, inst)

    dbus_client = get_dbus_client()
    data: GridData = await dbus_client.get_grid_data(instance)
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
    if _use_mqtt():
        client = await _mqtt_ready()
        dtype, inst = _resolve_mqtt_instance(client, ("vebus",), instance)
        return {"instance": inst} | _collect_mqtt(client, INVERTER_PATHS, dtype, inst)

    dbus_client = get_dbus_client()
    data: InverterData = await dbus_client.get_inverter_data(instance)
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
    """List all Victron devices visible to the server."""
    if _use_mqtt():
        client = await _mqtt_ready()
        return client.list_devices()

    dbus_client = get_dbus_client()
    return await dbus_client.list_devices()


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

    if _use_mqtt():
        client = await _mqtt_ready()
        code = _mode_code("vebus", mode)
        if code is None:
            return {
                "success": False,
                "error": f"mode '{mode}' has no known enum code for vebus devices",
            }
        return await _mqtt_write_and_verify(client, "vebus", instance, "Mode", code)

    return {"success": False, "error": "dbus writes not implemented"}


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

    if _use_mqtt():
        client = await _mqtt_ready()
        return await _mqtt_write_and_verify(
            client, "vebus", instance, "Dc/0/MaxChargeCurrent", current
        )

    return {"success": False, "error": "dbus writes not implemented"}


@mcp.tool()
async def set_soc_limit(
    soc_limit: int, instance: int = 0, confirmed: bool = False
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

    if _use_mqtt():
        client = await _mqtt_ready()
        # ponytail: /SocLimit assumed for target battery; confirm exact BMS
        # path on real hardware (TODO §4) before trusting read-back success.
        return await _mqtt_write_and_verify(client, "battery", instance, "SocLimit", soc_limit)

    return {"success": False, "error": "dbus writes not implemented"}


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

    Not yet implemented - returns an error.
    """
    return {
        "success": False,
        "error": "unsupported",
        "message": "MQTT subscribe not yet implemented",
    }
