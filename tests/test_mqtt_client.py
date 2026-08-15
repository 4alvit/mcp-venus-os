"""Tests for the MQTT client."""

from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import paho.mqtt.client as mqtt
import pytest
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from mcp_venus_os.config import MQTTConfig, ServerConfig
from mcp_venus_os.dbus_client import BatteryData, GridData, InverterData, PVData
from mcp_venus_os.mqtt_client import ConnectionTimeoutError, MQTTClient, NotConnectedError, Payload


def _noop(payload: Payload) -> None:
    """Callback that does nothing."""


class FakeReasonCode:
    def __init__(self, value: int) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, int) and self.value == other

    def __index__(self) -> int:
        return self.value


def test_topic_matches() -> None:
    client = MQTTClient()
    assert client._topic_matches("a/+/c", "a/b/c")
    assert client._topic_matches("#", "anything")
    assert not client._topic_matches("a/+/c", "a/b/d")
    assert not client._topic_matches("a/b", "a/b/c")
    assert not client._topic_matches("a/b/c", "a/b/c/d")


def test_on_connect_success() -> None:
    client = MQTTClient()
    paho_client = Mock()
    client._on_connect(
        cast(mqtt.Client, paho_client),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(0)),
        cast(Properties, Mock()),
    )
    assert client._connected
    assert paho_client.subscribe.call_count == 2


def test_on_connect_failure() -> None:
    client = MQTTClient()
    client._on_connect(
        cast(mqtt.Client, Mock()),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(1)),
        cast(Properties, Mock()),
    )
    assert not client._connected


def test_on_disconnect() -> None:
    client = MQTTClient()
    client._connected = True
    client._on_disconnect(
        cast(mqtt.Client, Mock()),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(1)),
        cast(Properties, Mock()),
    )
    assert not client._connected


def test_on_message_valid() -> None:
    client = MQTTClient()
    received: list[Payload] = []
    client.subscribe("N/venus-os/+/+", received.append)
    msg = mqtt.MQTTMessage()
    msg._topic = b"N/venus-os/battery/0"
    msg.payload = b'{"a": 1}'
    client._on_message(cast(mqtt.Client, Mock()), None, msg)
    assert received == [{"a": 1}]


def test_on_message_invalid_json() -> None:
    client = MQTTClient()
    msg = mqtt.MQTTMessage()
    msg._topic = b"N/venus-os/battery/0"
    msg.payload = b"not json"
    client._on_message(cast(mqtt.Client, Mock()), None, msg)


def test_on_message_decode_error() -> None:
    client = MQTTClient()
    msg = mqtt.MQTTMessage()
    msg._topic = b"N/venus-os/battery/0"
    msg.payload = b"\xff"
    client._on_message(cast(mqtt.Client, Mock()), None, msg)


def test_notify_callbacks_and_error() -> None:
    client = MQTTClient()
    calls: list[str] = []

    def good(payload: Payload) -> None:
        calls.append("good")

    def bad(payload: Payload) -> None:
        raise RuntimeError("boom")

    client.subscribe("a/b/c", good)
    client.subscribe("a/b/c", bad)
    client._notify_callbacks("a/b/c", {"x": 1})
    assert calls == ["good"]


def test_subscribe_new_and_existing() -> None:
    client = MQTTClient()
    client.subscribe("x/+", _noop)
    client.subscribe("x/+", _noop)
    assert client._callbacks["x/+"] == [_noop, _noop]


def test_subscribe_when_connected() -> None:
    client = MQTTClient()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    client.subscribe("y", _noop)
    paho_client.subscribe.assert_called_once_with("y")


def test_unsubscribe() -> None:
    client = MQTTClient()
    client.subscribe("z", _noop)
    client.unsubscribe("z", _noop)
    assert client._callbacks["z"] == []
    client.unsubscribe("missing", _noop)


def test_publish_not_connected() -> None:
    client = MQTTClient()
    with pytest.raises(NotConnectedError):
        client.publish("x/y", {"a": 1})


def test_publish_dict_payload() -> None:
    client = MQTTClient()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    client.publish("x/y", {"a": 1}, retain=True)
    paho_client.publish.assert_called_once_with("N/venus-os/x/y", '{"a": 1}', retain=True)


def test_publish_string_payload() -> None:
    client = MQTTClient()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    client.publish("x/y", "hello")
    paho_client.publish.assert_called_once_with("N/venus-os/x/y", "hello", retain=False)


def test_publish_helpers() -> None:
    client = MQTTClient()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    client.publish_battery(0, BatteryData(50.0, 13.0, 5.0, 65.0, 20.0, "Discharging"))
    client.publish_pv(0, PVData(100.0, 50.0, 2.0, 10.0, 1000.0))
    client.publish_grid(0, GridData(200.0, 230.0, 1.0, 50.0, "ok"))
    client.publish_inverter(0, InverterData("on", "running", 500.0, 0.0, 600.0, 35.0))
    assert paho_client.publish.call_count == 4


@pytest.mark.asyncio
async def test_connect_success() -> None:
    with patch("mcp_venus_os.mqtt_client.mqtt.Client") as mock_client_cls:
        client = MQTTClient()
        mock_client_cls.return_value.connect_async.side_effect = lambda _host, _port: setattr(
            client, "_connected", True
        )
        await client.connect()
        await client.connect()
    mock_client_cls.return_value.loop_start.assert_called_once()
    mock_client_cls.return_value.connect_async.assert_called_once_with("localhost", 1883)


@pytest.mark.asyncio
async def test_connect_timeout() -> None:
    with (
        patch("mcp_venus_os.mqtt_client.mqtt.Client") as mock_client_cls,
        patch("mcp_venus_os.mqtt_client.asyncio.sleep", new=AsyncMock()),
    ):
        client = MQTTClient()
        with pytest.raises(ConnectionTimeoutError):
            await client.connect()
    mock_client_cls.return_value.loop_start.assert_called_once()


@pytest.mark.asyncio
async def test_connect_with_auth_and_tls() -> None:
    config = ServerConfig(
        mqtt=MQTTConfig(host="broker", port=8883, username="u", password="p", tls=True)
    )
    with (
        patch("mcp_venus_os.mqtt_client.get_config", return_value=config),
        patch("mcp_venus_os.mqtt_client.mqtt.Client") as mock_client_cls,
    ):
        client = MQTTClient()
        mock_client_cls.return_value.connect_async.side_effect = lambda _host, _port: setattr(
            client, "_connected", True
        )
        await client.connect()
    mock_client_cls.return_value.username_pw_set.assert_called_once_with("u", "p")
    mock_client_cls.return_value.tls_set.assert_called_once()
    mock_client_cls.return_value.connect_async.assert_called_once_with("broker", 8883)


@pytest.mark.asyncio
async def test_disconnect() -> None:
    client = MQTTClient()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    await client.disconnect()
    paho_client.loop_stop.assert_called_once()
    paho_client.disconnect.assert_called_once()
    assert not client._connected


@pytest.mark.asyncio
async def test_disconnect_not_connected() -> None:
    client = MQTTClient()
    await client.disconnect()
