"""Shared MQTT read paths and bounded broker-side telemetry selection."""

from collections.abc import Iterable

from paho.mqtt.client import topic_matches_sub

from .hardware_contracts import HardwareWriteContract

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


READ_PATHS = {
    "battery": BATTERY_PATHS,
    "solarcharger": PV_PATHS,
    "pvinverter": PV_PATHS,
    "grid": GRID_PATHS,
    "vebus": INVERTER_PATHS,
}

# These internal services expose no top-level item or Mgmt identity. Keep one
# small discovery marker per family instead of their settings/history trees.
DISCOVERY_PATHS = {
    "digitalinputs": "Devices/+/Type",
    "logger": "Storage/MountState",
    "modbustcp": "Services/Count",
    "settings": "Settings/Vrmlogger/LogInterval",
}


def contract_topics(prefix: str, contracts: list[HardwareWriteContract]) -> set[str]:
    """Exact contract targets/identities for this portal, including deeper paths."""
    topics: set[str] = set()
    for contract in contracts:
        if prefix != f"N/{contract.portal_id}":
            continue
        topics.add(f"{prefix}/{contract.device_type}/{contract.instance}/{contract.path}")
        topics.update(
            f"{prefix}/{probe.device_type}/{probe.instance}/{probe.path}"
            for probe in contract.identity
        )
    return topics


def subscriptions(prefix: str, contracts: list[HardwareWriteContract]) -> set[str]:
    """Keep service discovery broad without receiving unconsumed nested trees."""
    filters = {f"{prefix}/+/+/+", f"{prefix}/+/+/Mgmt/+", f"{prefix}/full_publish_completed"}
    filters.update(f"{prefix}/{family}/+/{path}" for family, path in DISCOVERY_PATHS.items())
    for device_type, fields in READ_PATHS.items():
        for paths in fields.values():
            filters.update(f"{prefix}/{device_type}/+/{path}" for path in paths if "/" in path)
    for topic in contract_topics(prefix, contracts):
        # Avoid duplicate broker deliveries when discovery or a tool filter
        # already covers this exact target/identity.
        if not any(topic_matches_sub(pattern, topic) for pattern in filters):
            filters.add(topic)
    return filters


def refresh_topics(
    prefix: str,
    cached: Iterable[str],
    contracts: list[HardwareWriteContract],
    explicit: Iterable[str],
) -> list[str]:
    """Select exact cached values whose freshness is consumed by this client.

    Discovery-only values are not republished periodically. The caller must use
    a suppressed keepalive payload when reading the legacy system/0/Serial alias.
    """
    required = contract_topics(prefix, contracts)
    required.update(topic for topic in explicit if "+" not in topic and "#" not in topic)
    targets: set[str] = set()
    for topic in cached:
        if not topic.startswith(prefix + "/"):
            continue
        parts = topic[len(prefix) + 1 :].split("/", 2)
        if len(parts) != 3 or not parts[1].isdigit():
            continue
        family, _, path = parts
        fields = READ_PATHS.get(family, {})
        if topic in required or any(path in candidates for candidates in fields.values()):
            targets.add(topic)
    return sorted(targets)
