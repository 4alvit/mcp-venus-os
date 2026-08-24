"""Service detection from the MQTT broker cache.

The Cerbo broker carries more than the Venus gateway tree: companion
services (inverter-control, dbus-pump, …) publish their own topics on the
same broker. Tools for those services are registered only when their
markers are actually seen, so an installation without a service never
advertises its tool to clients (saves client context).
"""

from collections.abc import Iterable

# capability -> topic markers (exact or prefix) matched against non-Venus,
# top-level topics (anything outside N/<portalId>/… and W/<portalId>/…)
CAPABILITY_MARKERS: dict[str, tuple[str, ...]] = {
    "control": ("inverter/state",),  # inverter-control MQTT bridge
    "pump": ("tank/",),  # dbus-pump tank service
}

# Venus gateway prefixes that never count toward companion-service detection
_VENUS_PREFIXES = ("N/", "W/", "R/")


def is_capability_topic(topic: str) -> bool:
    """True when ``topic`` belongs to a companion service (worth caching)."""
    if topic.startswith(_VENUS_PREFIXES):
        return False
    return any(
        topic == marker or (marker.endswith("/") and topic.startswith(marker))
        for markers in CAPABILITY_MARKERS.values()
        for marker in markers
    )


def capability_subscriptions() -> list[str]:
    """MQTT subscription patterns covering every capability marker."""
    return [
        f"{marker}#" if marker.endswith("/") else marker
        for markers in CAPABILITY_MARKERS.values()
        for marker in markers
    ]


def detect_capabilities(topics: Iterable[str]) -> set[str]:
    """Capabilities whose marker topics are present in ``topics``."""
    caps: set[str] = set()
    for topic in topics:
        if not is_capability_topic(topic):
            continue
        for cap, markers in CAPABILITY_MARKERS.items():
            if any(topic == m or (m.endswith("/") and topic.startswith(m)) for m in markers):
                caps.add(cap)
    return caps
