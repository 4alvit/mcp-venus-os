import json
from unittest.mock import Mock, patch

import pytest

from mcp_venus_os import server as server_module
from mcp_venus_os.safety import SafetyCheckResult
from mcp_venus_os.server import (
    _values_match,
    set_charge_current_limit,
    set_inverter_mode,
    set_soc_limit,
)


@pytest.mark.asyncio
async def test_set_inverter_mode_requires_confirmation() -> None:
    # When confirmed=False, safety validator returns not allowed and requires confirmation
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=True,
            reason="Test reason",
            confirmation_message="Please confirm",
        )

        result = await set_inverter_mode(mode="on", instance=0, confirmed=False)

        assert result["success"] is False
        assert result["requires_confirmation"] is True
        assert result["confirmation_message"] == "Please confirm"


@pytest.mark.asyncio
async def test_set_inverter_mode_not_allowed() -> None:
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=False,
            reason="Not allowed",
            confirmation_message="",
        )

        result = await set_inverter_mode(mode="on", instance=0, confirmed=True)

        assert result["success"] is False
        assert result["error"] == "Not allowed"


@pytest.mark.asyncio
async def test_set_charge_current_limit_not_allowed() -> None:
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=False,
            reason="Not allowed",
            confirmation_message="",
        )

        result = await set_charge_current_limit(current=10.0, instance=0, confirmed=True)

        assert result["success"] is False
        assert result["error"] == "Not allowed"


@pytest.mark.asyncio
async def test_set_soc_limit_requires_confirmation() -> None:
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=True,
            reason="Test reason",
            confirmation_message="Please confirm",
        )

        result = await set_soc_limit(soc_limit=80, instance=0, confirmed=False)

        assert result["success"] is False
        assert result["requires_confirmation"] is True
        assert result["confirmation_message"] == "Please confirm"


@pytest.mark.asyncio
async def test_set_soc_limit_not_allowed() -> None:
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=False,
            reason="Not allowed",
            confirmation_message="",
        )

        result = await set_soc_limit(soc_limit=80, instance=0, confirmed=True)

        assert result["success"] is False
        assert result["error"] == "Not allowed"


# --- MQTT write-path tests --------------------------------------------------

import time as _time  # noqa: E402
from typing import Any, cast  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

from mcp_venus_os.config import MQTTConfig, ServerConfig  # noqa: E402
from mcp_venus_os.mqtt_client import MQTTClient, Payload  # noqa: E402


def _mqtt_client(portal: str = "testportal") -> MQTTClient:
    cfg = ServerConfig(mqtt=MQTTConfig(host="localhost", portal_id=portal))
    with patch("mcp_venus_os.mqtt_client.get_config", return_value=cfg):
        client = MQTTClient()
    # Simulate post-warm-up state so _mqtt_ready doesn't wait for the
    # gateway's full-publish marker.
    client._cache[f"N/{portal}/full_publish_completed"] = ({"value": 1}, _time.monotonic())
    cast(Any, client).connect = AsyncMock()
    for contract in server_module.get_safety_validator().config.hardware_write_contracts:
        for probe in contract.identity:
            _seed_cache(
                client,
                f"N/{portal}/{probe.device_type}/{probe.instance}/{probe.path}",
                probe.expected,
            )
    return client


def _seed_cache(client: MQTTClient, topic: str, value: Payload) -> None:
    client._cache[topic] = (value, _time.monotonic())


def _echo_writes(client: MQTTClient, paho: Mock) -> None:
    """An actual response arrives after publishing; a pre-seeded value is not an ack."""

    def publish(topic: str, payload: str, retain: bool = False) -> None:
        if topic.startswith("W/"):
            _seed_cache(client, "N/" + topic[2:], json.loads(payload)["value"])

    paho.publish.side_effect = publish


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "code"),
    [("charger_only", 1), ("inverter_only", 2), ("on", 3), ("off", 4)],
)
async def test_set_inverter_mode_mqtt_publishes_and_verifies(
    enable_writes: None,  # noqa: ARG001
    mode: str,
    code: int,
) -> None:
    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True
    _echo_writes(client, paho)

    with (
        patch("mcp_venus_os.server.get_mqtt_client", return_value=client),
        patch("mcp_venus_os.mqtt_client.asyncio.create_task") as background,
    ):
        result = await set_inverter_mode(mode=mode, instance=256, confirmed=True)

    assert result["success"] is True
    assert result["value"] == code
    assert result["topic"] == "W/testportal/vebus/256/Mode"
    assert result["automatic_rollback"] is False
    paho.publish.assert_called_once_with(
        "W/testportal/vebus/256/Mode", json.dumps({"value": code}), retain=False
    )
    background.assert_not_called()


@pytest.mark.asyncio
async def test_set_inverter_mode_unknown_enum_rejected_before_publish(
    enable_writes: None,  # noqa: ARG001
) -> None:
    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True

    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await set_inverter_mode(mode="eco", instance=0, confirmed=True)

    assert result["success"] is False
    assert "no known enum code" in result["error"]
    paho.publish.assert_not_called()


@pytest.mark.asyncio
async def test_set_charge_current_limit_mqtt_publishes_and_verifies(
    enable_writes: None,  # noqa: ARG001
) -> None:
    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True
    _echo_writes(client, paho)

    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await set_charge_current_limit(current=50.0, instance=256, confirmed=True)

    assert result["success"] is True
    paho.publish.assert_any_call(
        "W/testportal/vebus/256/Dc/0/MaxChargeCurrent", '{"value": 50.0}', retain=False
    )


@pytest.mark.asyncio
async def test_set_soc_limit_mqtt_publishes_to_battery_path(
    enable_writes: None,  # noqa: ARG001
) -> None:
    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True
    _echo_writes(client, paho)

    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await set_soc_limit(soc_limit=80, instance=512, confirmed=True)

    assert result["success"] is True
    paho.publish.assert_any_call("W/testportal/battery/512/SocLimit", '{"value": 80}', retain=False)


@pytest.mark.asyncio
async def test_write_readback_timeout_reports_error(
    enable_writes: None,  # noqa: ARG001
) -> None:
    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True

    async def _no_sleep(_seconds: float) -> None:
        """Skip verification polling delay."""

    with (
        patch("mcp_venus_os.server.get_mqtt_client", return_value=client),
        patch("mcp_venus_os.server.asyncio.sleep", side_effect=_no_sleep),
    ):
        result = await set_soc_limit(soc_limit=80, instance=512, confirmed=True)

    assert result["success"] is False
    assert "did not reflect it" in result["error"]


def test_values_match_unwraps_gateway_value_dict() -> None:
    """Gateway echoes items as {"value": …} dicts on N topics."""
    assert _values_match({"max": 52.0, "value": 45.0}, 45.0)
    assert not _values_match({"value": 52.0}, 45.0)
    assert not _values_match({"max": 52.0}, 52.0)
    assert _values_match(3, 3)
    assert _values_match("50", 50.0)


def test_cache_since_rejects_matching_values_received_before_a_write() -> None:
    """Compare ingestion timestamps directly, without a timing-tolerance race."""
    client = _mqtt_client()
    started = _time.monotonic()
    topic = "N/testportal/vebus/256/Mode"
    client._cache[topic] = (1, started - 0.000001)
    assert client.read_path_since("vebus", 256, "Mode", started) is None
    client._cache[topic] = (1, started)
    assert client.read_path_since("vebus", 256, "Mode", started) is not None


@pytest.mark.asyncio
async def test_queued_prewrite_message_cannot_acknowledge_a_new_write(enable_writes: None) -> None:
    """Reproduce a matching old message decoded only after command publication."""
    import paho.mqtt.client as mqtt

    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True
    msg = mqtt.MQTTMessage()
    msg._topic = b"N/testportal/vebus/256/Mode"
    msg.payload = b'{"value": 3}'
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=_time.monotonic() - 10):
        client._on_message(cast(Any, paho), None, msg)
    paho.publish.side_effect = lambda *_args, **_kwargs: client._drain_inbox()
    with (
        patch("mcp_venus_os.server.get_mqtt_client", return_value=client),
        patch("mcp_venus_os.server.WRITE_VERIFY_TIMEOUT_S", 0.01),
    ):
        result = await set_inverter_mode(mode="on", instance=256, confirmed=True)
    assert result["success"] is False
    assert "did not reflect" in result["error"]
