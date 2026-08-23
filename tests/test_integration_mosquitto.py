"""Integration test against a real mosquitto broker simulating the Venus topic layout.

Skipped unless a Docker daemon is available (the CI runner has one).
"""

import socket
import subprocess
import time
from typing import cast
from unittest.mock import patch

import pytest

from mcp_venus_os.config import MQTTConfig, ServerConfig
from mcp_venus_os.mqtt_client import Payload

pytest.importorskip("subprocess")  # always true; keeps module import-safe

PORTAL = "integrationportal"
IMAGE = "eclipse-mosquitto:2"


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def broker_port() -> object:
    if not _docker_available():
        pytest.skip("docker not available")
    port = _free_port()
    name = f"mcp-venus-os-test-mosquitto-{port}"
    up = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"{port}:1883",
            IMAGE,
            "mosquitto",
            "-c",
            "/mosquitto-no-auth.conf",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert up.returncode == 0, up.stderr
    # Wait for the broker to accept connections
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    else:
        subprocess.run(["docker", "stop", name], capture_output=True)
        subprocess.run(["docker", "rm", name], capture_output=True)
        pytest.fail("mosquitto did not start listening in time")
    yield port
    subprocess.run(["docker", "stop", name], capture_output=True)
    subprocess.run(["docker", "rm", name], capture_output=True)


def _publish(port: int, topic: str, payload: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "exec",
            f"mcp-venus-os-test-mosquitto-{port}",
            "mosquitto_pub",
            "-h",
            "localhost",
            "-t",
            topic,
            "-m",
            payload,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_read_and_write_roundtrip_over_real_broker(broker_port: object) -> None:
    """Fake Venus publishes N/ telemetry; tools read it; writes appear on W/."""
    port = cast(int, broker_port)
    cfg = ServerConfig(mqtt=MQTTConfig(host="127.0.0.1", port=port, portal_id=PORTAL))

    import mcp_venus_os.mqtt_client as mqtt_module

    def _noop(_payload: Payload) -> None:
        """Callback that does nothing."""

    with (
        patch.object(mqtt_module, "get_config", return_value=cfg),
        patch.object(mqtt_module, "KEEPALIVE_INTERVAL_S", 3600),
    ):
        client = mqtt_module.MQTTClient()
        await client.connect()

    # Simulate Venus publishing telemetry on N/…
    telemetry = {
        f"N/{PORTAL}/battery/256/Soc": "55.5",
        f"N/{PORTAL}/battery/256/Dc/0/Voltage": "13.2",
        f"N/{PORTAL}/system/0/Ac/Grid/Power": "-1234",
        f"N/{PORTAL}/vebus/257/Mode": "1",
    }
    for topic, payload in telemetry.items():
        _publish(port, topic, payload)
    time.sleep(0.5)  # allow the client to receive

    soc = client.read_path("battery", 256, "Soc")
    assert soc is not None
    assert soc[0] == 55.5
    devices = client.list_devices()
    assert {"device_type": "battery", "instance": 256} in devices
    assert {"device_type": "system", "instance": 0} in devices
    assert {"device_type": "vebus", "instance": 257} in devices

    # Write path: subscribe to W/… first (no retain), then publish and confirm echo
    seen = {"done": False}

    def _on_w(payload: Payload) -> None:
        if payload == 4:
            seen["done"] = True

    client.subscribe(f"W/{PORTAL}/#", _on_w)
    time.sleep(0.3)  # let SUBACK land so our own publish echoes back
    item_topic = f"W/{PORTAL}/vebus/256/Mode"
    client.publish(item_topic, 4)
    for _ in range(20):
        if seen["done"]:
            break
        time.sleep(0.2)
    assert seen["done"], "write to W/… never reached the broker"
    await client.disconnect()
