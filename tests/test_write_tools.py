from unittest.mock import Mock, patch

import pytest

from mcp_venus_os.safety import SafetyCheckResult
from mcp_venus_os.server import (
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
    return client


def _seed_cache(client: MQTTClient, topic: str, value: Payload) -> None:
    client._cache[topic] = (value, _time.monotonic())


@pytest.mark.asyncio
async def test_set_inverter_mode_mqtt_publishes_and_verifies() -> None:
    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True
    # Venus echoes the new value back on N/…; pre-seed so read-back verifies instantly
    _seed_cache(client, "N/testportal/vebus/256/Mode", 1)

    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await set_inverter_mode(mode="on", instance=256, confirmed=True)

    assert result["success"] is True
    assert result["value"] == 1
    assert result["topic"] == "W/testportal/vebus/256/Mode"
    paho.publish.assert_any_call("W/testportal/vebus/256/Mode", "1", retain=False)
    assert any(t.endswith("/Keepalive") for t in client._keepalives), "keepalive must be armed"
    client.cancel_keepalives()


@pytest.mark.asyncio
async def test_set_inverter_mode_unknown_enum_rejected_before_publish() -> None:
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
async def test_set_charge_current_limit_mqtt_publishes_and_verifies() -> None:
    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True
    _seed_cache(client, "N/testportal/vebus/256/Dc/0/MaxChargeCurrent", 50.0)

    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await set_charge_current_limit(current=50.0, instance=256, confirmed=True)

    assert result["success"] is True
    paho.publish.assert_any_call(
        "W/testportal/vebus/256/Dc/0/MaxChargeCurrent", "50.0", retain=False
    )
    client.cancel_keepalives()


@pytest.mark.asyncio
async def test_set_soc_limit_mqtt_publishes_to_battery_path() -> None:
    client = _mqtt_client()
    paho = Mock()
    client.client = cast(Any, paho)
    client._connected = True
    _seed_cache(client, "N/testportal/battery/512/SocLimit", 80)

    with patch("mcp_venus_os.server.get_mqtt_client", return_value=client):
        result = await set_soc_limit(soc_limit=80, instance=512, confirmed=True)

    assert result["success"] is True
    paho.publish.assert_any_call("W/testportal/battery/512/SocLimit", "80", retain=False)
    client.cancel_keepalives()


@pytest.mark.asyncio
async def test_write_readback_timeout_reports_error() -> None:
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
    client.cancel_keepalives()
