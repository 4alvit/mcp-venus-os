"""Tests for the MQTT client."""

import asyncio
import contextlib
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import paho.mqtt.client as mqtt
import pytest
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from mcp_venus_os.config import MQTTConfig, ServerConfig
from mcp_venus_os.mqtt_client import (
    ConnectionTimeoutError,
    MQTTClient,
    NotConnectedError,
    Payload,
)

PORTAL = "testportal"
PREFIX = f"N/{PORTAL}"


def _config(**overrides: object) -> ServerConfig:
    mqtt_kwargs: dict[str, object] = {"host": "localhost", "port": 1883, "portal_id": PORTAL}
    mqtt_kwargs.update(overrides)
    return ServerConfig(mqtt=MQTTConfig(**mqtt_kwargs))  # type: ignore[arg-type]


def _make_client(**config_overrides: object) -> MQTTClient:
    """MQTT client backed by a test config with a fixed portal id."""
    with patch("mcp_venus_os.mqtt_client.get_config", return_value=_config(**config_overrides)):
        return MQTTClient()


def _noop(payload: Payload) -> None:
    """Callback that does nothing."""


class FakeReasonCode:
    def __init__(self, value: int) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, int) and self.value == other

    def __index__(self) -> int:
        return self.value


def _feed(client: MQTTClient, topic: str, payload: bytes) -> None:
    msg = mqtt.MQTTMessage()
    msg._topic = topic.encode()
    msg.payload = payload
    client._on_message(cast(mqtt.Client, Mock()), None, msg)
    client._drain_inbox()


def test_topic_matches() -> None:
    client = _make_client()
    assert client._topic_matches("a/+/c", "a/b/c")
    assert client._topic_matches("#", "anything")
    assert client._topic_matches("a/#", "a/b/c/d")
    assert not client._topic_matches("b/#", "a/b/c")
    assert not client._topic_matches("a/+/c", "a/b/d")
    assert not client._topic_matches("a/b", "a/b/c")
    assert not client._topic_matches("a/b/c", "a/b/c/d")


def test_on_connect_success_subscribes_portal_wildcard() -> None:
    client = _make_client()
    paho_client = Mock()
    client._on_connect(
        cast(mqtt.Client, paho_client),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(0)),
        cast(Properties, Mock()),
    )
    assert client._connected
    subs = [c.args[0] for c in paho_client.subscribe.call_args_list]
    assert subs[0] == f"{PREFIX}/#"
    # companion-service subscriptions ride along (inverter-control, dbus-pump)
    assert "inverter/state" in subs
    assert "tank/#" in subs


def test_on_connect_failure() -> None:
    client = _make_client()
    client._on_connect(
        cast(mqtt.Client, Mock()),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(1)),
        cast(Properties, Mock()),
    )
    assert not client._connected


def test_on_disconnect() -> None:
    client = _make_client()
    client._connected = True
    client._on_disconnect(
        cast(mqtt.Client, Mock()),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(1)),
        cast(Properties, Mock()),
    )
    assert not client._connected


def test_on_message_valid_caches_value() -> None:
    client = _make_client()
    received: list[Payload] = []
    client.subscribe(f"{PREFIX}/#", received.append)
    _feed(client, f"{PREFIX}/battery/0/Soc", b"55.5")
    assert received == [55.5]
    cached = client.read_path("battery", 0, "Soc")
    assert cached is not None
    assert cached[0] == 55.5


def test_on_message_outside_prefix_not_cached() -> None:
    client = _make_client()
    _feed(client, "N/otherportal/battery/0/Soc", b"42")
    assert client.read_path("battery", 0, "Soc") is None


def test_on_message_invalid_json() -> None:
    client = _make_client()
    _feed(client, f"{PREFIX}/battery/0", b"not json")
    assert client._cache == {}


def test_on_message_decode_error() -> None:
    client = _make_client()
    _feed(client, f"{PREFIX}/battery/0", b"\xff")
    assert client._cache == {}


def test_notify_callbacks_and_error() -> None:
    client = _make_client()
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
    client = _make_client()
    client.subscribe("x/+", _noop)
    client.subscribe("x/+", _noop)
    assert client._callbacks["x/+"] == [_noop, _noop]


def test_subscribe_when_connected() -> None:
    client = _make_client()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    client.subscribe("y", _noop)
    paho_client.subscribe.assert_called_once_with("y")


def test_unsubscribe() -> None:
    client = _make_client()
    client.subscribe("z", _noop)
    client.unsubscribe("z", _noop)
    assert client._callbacks["z"] == []
    client.unsubscribe("missing", _noop)


def test_publish_not_connected() -> None:
    client = _make_client()
    with pytest.raises(NotConnectedError):
        client.publish("x/y", {"a": 1})


def test_publish_uses_absolute_topic() -> None:
    client = _make_client()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    client.publish("W/testportal/battery/512/Soc", 50, retain=True)
    paho_client.publish.assert_called_once_with("W/testportal/battery/512/Soc", "50", retain=True)


def test_publish_string_payload() -> None:
    client = _make_client()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    client.publish("W/testportal/x/y", "hello")
    paho_client.publish.assert_called_once_with("W/testportal/x/y", "hello", retain=False)


def test_read_path_returns_age() -> None:
    client = _make_client()
    assert client.read_path("battery", 256, "Soc") is None
    _feed(client, f"{PREFIX}/battery/256/Soc", b"55.5")
    result = client.read_path("battery", 256, "Soc")
    assert result is not None
    value, age = result
    assert value == 55.5
    assert 0.0 <= age < 1.0


def test_read_first_prefers_first_available_candidate() -> None:
    client = _make_client()
    _feed(client, f"{PREFIX}/battery/256/Dc/0/Voltage", b"13.2")
    result = client.read_first("battery", 256, ["Voltage", "Dc/0/Voltage"])
    assert result is not None
    assert result[0] == 13.2


def test_list_devices_from_cache() -> None:
    client = _make_client()
    for topic in (
        f"{PREFIX}/battery/256/Soc",
        f"{PREFIX}/battery/256/Dc/0/Voltage",
        f"{PREFIX}/solarcharger/1/Yield/Power",
        f"{PREFIX}/vebus/257/Ac/Out/P",
        f"{PREFIX}/system/0/Serial",
    ):
        _feed(client, topic, b"1")
    devices = client.list_devices()
    assert devices == [
        {"device_type": "battery", "instance": 256},
        {"device_type": "solarcharger", "instance": 1},
        {"device_type": "system", "instance": 0},
        {"device_type": "vebus", "instance": 257},
    ]


def test_list_devices_skips_non_numeric_instances() -> None:
    client = _make_client()
    _feed(client, f"{PREFIX}/settings/Settings", b"{}")
    assert client.list_devices() == []


def test_stale_after_seconds_configured() -> None:
    client = _make_client(stale_after_seconds=5.0)
    assert client.config.stale_after_seconds == 5.0


def test_topic_prefix_requires_portal_id() -> None:
    from mcp_venus_os.config import MissingPortalIdError

    with pytest.raises(MissingPortalIdError):
        _ = MQTTConfig().topic_prefix


@pytest.mark.asyncio
async def test_connect_success() -> None:
    with patch("mcp_venus_os.mqtt_client.mqtt.Client") as mock_client_cls:
        client = _make_client()
        mock_client_cls.return_value.connect_async.side_effect = lambda _host, _port, **_kw: (
            setattr(client, "_connected", True)
        )
        await client.connect()
        await client.connect()
    mock_client_cls.return_value.loop_start.assert_called_once()
    mock_client_cls.return_value.connect_async.assert_called_once_with(
        "localhost", 1883, keepalive=30
    )


@pytest.mark.asyncio
async def test_connect_timeout() -> None:
    with (
        patch("mcp_venus_os.mqtt_client.get_config", return_value=_config()),
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
        mqtt=MQTTConfig(
            host="broker",
            port=8883,
            username="u",
            password="p",
            tls=True,
            portal_id="p1",
        )
    )
    with (
        patch("mcp_venus_os.mqtt_client.get_config", return_value=config),
        patch("mcp_venus_os.mqtt_client.mqtt.Client") as mock_client_cls,
    ):
        client = MQTTClient()
        mock_client_cls.return_value.connect_async.side_effect = lambda _host, _port, **_kw: (
            setattr(client, "_connected", True)
        )
        await client.connect()
    mock_client_cls.return_value.username_pw_set.assert_called_once_with("u", "p")
    mock_client_cls.return_value.tls_set.assert_called_once()
    mock_client_cls.return_value.connect_async.assert_called_once_with("broker", 8883, keepalive=30)


@pytest.mark.asyncio
async def test_disconnect() -> None:
    client = _make_client()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    await client.disconnect()
    paho_client.loop_stop.assert_called_once()
    paho_client.disconnect.assert_called_once()
    assert not client._connected


@pytest.mark.asyncio
async def test_disconnect_not_connected() -> None:
    client = _make_client()
    await client.disconnect()


def test_write_prefix() -> None:
    client = _make_client()
    assert client.write_prefix == f"W/{PORTAL}"


@pytest.mark.asyncio
async def test_start_keepalive_publishes_periodically() -> None:
    client = _make_client()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True
    with patch("mcp_venus_os.mqtt_client.KEEPALIVE_INTERVAL_S", 0.01):
        client.start_keepalive(f"W/{PORTAL}/battery/512/Soc")
        await asyncio.sleep(0.05)
        client.cancel_keepalives()
    keepalive_calls = [
        c for c in paho_client.publish.call_args_list if c.args[0].endswith("/Keepalive")
    ]
    assert len(keepalive_calls) >= 1
    assert keepalive_calls[0].args[1] == ""


@pytest.mark.asyncio
async def test_disconnect_cancels_keepalives() -> None:
    client = _make_client()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._connected = True

    async def _spin() -> None:
        await asyncio.sleep(10)

    task = asyncio.create_task(_spin())
    client._keepalives["W/x"] = task
    await client.disconnect()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert client._keepalives == {}
    assert task.cancelled()


def _raw_msg(topic: str, payload: bytes) -> mqtt.MQTTMessage:
    msg = mqtt.MQTTMessage()
    msg._topic = topic.encode()
    msg.payload = payload
    return msg


def test_worker_thread_processes_enqueued_messages() -> None:
    import time as time_mod

    client = _make_client()
    received: list[Payload] = []
    client.subscribe(f"{PREFIX}/#", received.append)
    client._start_worker()
    try:
        client._on_message(
            cast(mqtt.Client, Mock()), None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"55.5")
        )
        deadline = time_mod.monotonic() + 2.0
        while not received and time_mod.monotonic() < deadline:
            time_mod.sleep(0.01)
        assert received == [55.5]
        assert client.read_path("battery", 0, "Soc") is not None
    finally:
        if client._worker is not None and client._worker.is_alive():
            client._inbox.put(None)
            client._worker.join(timeout=1)


def test_inbox_overflow_drops_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mcp_venus_os.mqtt_client.INBOX_MAXSIZE", 1)
    client = _make_client()
    # Fill the queue (maxsize=1) without draining; the next message must be
    # dropped silently instead of raising inside paho's network thread.
    client._on_message(cast(mqtt.Client, Mock()), None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"1"))
    client._on_message(cast(mqtt.Client, Mock()), None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"2"))
    client._drain_inbox()
    assert client.read_path("battery", 0, "Soc") is not None
    assert client.read_path("battery", 0, "Soc")[0] == 1


def test_empty_payload_not_logged_as_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    client = _make_client()
    with caplog.at_level(logging.WARNING, logger="mcp_venus_os.mqtt_client"):
        _feed(client, f"{PREFIX}/acload/71/ProductName", b"")
        _feed(client, f"{PREFIX}/acload/71/ProductName", b"not json")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # Empty payload (Venus value expiry) is silent; real garbage still warns.
    assert len(warnings) == 1
