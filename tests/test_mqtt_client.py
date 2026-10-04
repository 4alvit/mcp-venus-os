"""Tests for the MQTT client."""

import asyncio
import json
import threading
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import paho.mqtt.client as mqtt
import pytest
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from mcp_venus_os.config import MQTTConfig, ServerConfig
from mcp_venus_os.hardware_contracts import HardwareWriteContract
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


def _callback_transport(client: MQTTClient) -> mqtt.Client:
    if client.client is None:
        client.client = cast(mqtt.Client, Mock())
    return client.client


def _mock_transport(*, auto_connect: bool = True) -> Mock:
    transport = Mock()
    transport.stopped = threading.Event()
    transport.entered = threading.Event()

    def network_loop(timeout: float, retry_first_connection: bool = False) -> None:
        transport.entered.set()
        if auto_connect:
            transport.on_connect(transport, None, None, FakeReasonCode(0), None)
        transport.stopped.wait(timeout=10)

    transport.loop_forever.side_effect = network_loop
    transport.disconnect.side_effect = transport.stopped.set
    return transport


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
    client._on_message(_callback_transport(client), None, msg)
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


@pytest.mark.parametrize(
    ("pattern", "topic", "matches"),
    [
        ("N/+/battery/+/#", "N/testportal/battery/0/Soc", True),
        ("a/+/#", "a/b", True),
        ("a/+/#", "a//c", True),
        ("a/+/#", "a", False),
        ("#", "$SYS/status", False),
        ("+/status", "$SYS/status", False),
        ("$SYS/#", "$SYS/status", True),
        ("a/+/#", "a/$device/state", True),
    ],
)
def test_callback_filter_semantics(pattern: str, topic: str, matches: bool) -> None:
    client = _make_client()
    received: list[Payload] = []
    client.subscribe(pattern, received.append)
    client._notify_callbacks(topic, 42)
    assert received == ([42] if matches else [])
    assert client._topic_matches(pattern, topic) is matches


def test_callback_dispatch_preserves_filter_and_callback_registration_order() -> None:
    client = _make_client()
    calls: list[str] = []
    client.subscribe("#", lambda _: calls.append("first"))
    client.subscribe("a/b", lambda _: calls.append("exact"))
    client.subscribe("a/+", lambda _: calls.append("single"))
    client.subscribe("#", lambda _: calls.append("duplicate filter"))
    client._notify_callbacks("a/b", None)
    assert calls == ["first", "duplicate filter", "exact", "single"]


def test_callback_subscription_changes_apply_to_next_message() -> None:
    client = _make_client()
    calls: list[str] = []

    def removed(payload: Payload) -> None:
        calls.append("removed")

    def added(payload: Payload) -> None:
        calls.append("added")

    def mutate(payload: Payload) -> None:
        calls.append("mutate")
        if payload == 1:
            client.unsubscribe("a/#", removed)
            client.subscribe("a/b", added)
            client.subscribe("a/#", added)

    client.subscribe("a/#", mutate)
    client.subscribe("a/#", removed)
    client._notify_callbacks("a/b", 1)
    assert calls == ["mutate", "removed"]
    calls.clear()
    client._notify_callbacks("a/b", 2)
    assert calls == ["mutate", "added", "added"]


def test_subscription_from_another_thread_does_not_block_running_callback() -> None:
    client = _make_client()
    entered = threading.Event()
    registered = threading.Event()
    calls: list[str] = []

    def callback(payload: Payload) -> None:
        entered.set()
        assert registered.wait(2), "callback must not hold the subscription lock"
        calls.append("original")

    def register() -> None:
        if entered.wait(2):
            client.subscribe("a/b", lambda _: calls.append("new"))
            registered.set()

    client.subscribe("a/#", callback)
    worker = threading.Thread(target=register)
    worker.start()
    try:
        client._notify_callbacks("a/b", None)
    finally:
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert registered.is_set()
    assert calls == ["original"]
    client._notify_callbacks("a/b", None)
    assert calls == ["original", "original", "new"]


def test_on_connect_success_subscribes_bounded_telemetry() -> None:
    client = _make_client()
    paho_client = Mock()
    client.client = cast(mqtt.Client, paho_client)
    client._on_connect(
        cast(mqtt.Client, paho_client),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(0)),
        cast(Properties, Mock()),
    )
    assert client._connected
    subs = [c.args[0] for c in paho_client.subscribe.call_args_list]
    assert f"{PREFIX}/#" not in subs
    assert f"{PREFIX}/+/+/+" in subs
    assert f"{PREFIX}/+/+/Mgmt/+" in subs
    assert f"{PREFIX}/full_publish_completed" in subs
    # companion-service subscriptions ride along (inverter-control, dbus-pump)
    assert "inverter/state" in subs
    assert "tank/#" in subs
    paho_client.publish.assert_called_once_with(f"R/{PORTAL}/keepalive", "", retain=False)


def test_reconnect_refreshes_telemetry_only_after_subscribing() -> None:
    client = _make_client()
    transport = Mock()
    client.client = cast(mqtt.Client, transport)
    for _ in range(2):
        transport.reset_mock()
        client._on_connect(
            cast(mqtt.Client, transport),
            None,
            None,
            cast(ReasonCode, FakeReasonCode(0)),
            cast(Properties, Mock()),
        )
        calls = transport.method_calls
        assert calls[0][0] == "subscribe"
        assert calls[-1][0] == "publish"
        transport.publish.assert_called_once_with(f"R/{PORTAL}/keepalive", "", retain=False)


def test_on_connect_failure() -> None:
    client = _make_client()
    transport = Mock()
    client.client = cast(mqtt.Client, transport)
    client._on_connect(
        cast(mqtt.Client, transport),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(1)),
        cast(Properties, Mock()),
    )
    assert not client._connected
    # No read refresh is sent when the broker rejects the connection.
    transport.publish.assert_not_called()


def test_on_disconnect() -> None:
    client = _make_client()
    client._connected = True
    client._on_disconnect(
        _callback_transport(client),
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
    assert "z" not in client._callbacks
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
    transport = _mock_transport()
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", return_value=transport) as factory:
        client = _make_client()
        await client.connect()
        await client.connect()
        await client.disconnect()
    factory.assert_called_once()
    transport.loop_forever.assert_called_once_with(timeout=5.0, retry_first_connection=True)
    transport.connect_async.assert_called_once_with("localhost", 1883, keepalive=30)


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
        await client.disconnect()
    mock_client_cls.return_value.loop_forever.assert_called_once_with(
        timeout=5.0, retry_first_connection=True
    )
    mock_client_cls.return_value.disconnect.assert_called_once()
    assert client._loop_thread is None
    assert client._worker is None


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
        patch(
            "mcp_venus_os.mqtt_client.mqtt.Client", return_value=_mock_transport()
        ) as mock_client_cls,
    ):
        client = MQTTClient()
        await client.connect()
        await client.disconnect()
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
    paho_client.disconnect.assert_called_once()
    assert not client._connected


@pytest.mark.asyncio
async def test_disconnect_not_connected() -> None:
    client = _make_client()
    await client.disconnect()


def test_write_prefix() -> None:
    client = _make_client()
    assert client.write_prefix == f"W/{PORTAL}"


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
            _callback_transport(client), None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"55.5")
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
    client._on_message(_callback_transport(client), None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"1"))
    client._on_message(_callback_transport(client), None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"2"))
    client._drain_inbox()
    cached = client.read_path("battery", 0, "Soc")
    assert cached is not None
    assert cached[0] == 1


def test_empty_payload_not_logged_as_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    client = _make_client()
    with caplog.at_level(logging.WARNING, logger="mcp_venus_os.mqtt_client"):
        _feed(client, f"{PREFIX}/acload/71/ProductName", b"")
        _feed(client, f"{PREFIX}/acload/71/ProductName", b"not json")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # Empty payload (device removal) is silent; real garbage still warns.
    assert len(warnings) == 1


def test_queued_telemetry_keeps_its_receive_age() -> None:
    """A slow decoder must not turn old identity data into a fresh observation."""
    client = _make_client()
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=10.0):
        client._on_message(
            _callback_transport(client), None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"55.5")
        )
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=70.0):
        client._drain_inbox()
        assert client.read_path("battery", 0, "Soc") == (55.5, 60.0)
        assert client.read_path_since("battery", 0, "Soc", 11.0) is None


def test_device_removal_invalidates_cached_identity_and_discovery() -> None:
    client = _make_client()
    topic = f"{PREFIX}/battery/256/ProductId"
    _feed(client, topic, b'{"value": 123}')
    assert client.discover_instance("battery") == 256
    _feed(client, topic, b"")
    assert client.read_path("battery", 256, "ProductId") is None
    assert client.discover_instance("battery") is None


def test_worker_drains_burst_in_order_without_one_sleep_per_message() -> None:
    """Full-tree bursts should not pay a scheduler wake-up for every value."""
    client = _make_client()
    received: list[Payload] = []
    client.subscribe(f"{PREFIX}/#", received.append)
    for number in range(256):
        client._on_message(
            _callback_transport(client),
            None,
            _raw_msg(f"{PREFIX}/battery/0/Soc", str(number).encode()),
        )
    client._inbox.put(None)
    with patch("mcp_venus_os.mqtt_client.time.sleep") as pause:
        client._process_inbox()
    assert received == list(range(256))
    assert 0 < pause.call_count <= 32


@pytest.mark.asyncio
async def test_disconnect_stops_network_worker_after_connection_loss() -> None:
    client = _make_client()
    entered = threading.Event()
    stopped = threading.Event()

    def network_loop(timeout: float, retry_first_connection: bool) -> None:
        client._connected = True
        entered.set()
        stopped.wait(timeout=2)

    with patch("mcp_venus_os.mqtt_client.mqtt.Client") as factory:
        transport = factory.return_value
        transport.loop_forever.side_effect = network_loop
        transport.disconnect.side_effect = stopped.set
        await client.connect()
        worker = client._loop_thread
        assert entered.wait(timeout=1)
        # A broker disconnect clears this flag before application shutdown.
        client._connected = False
        try:
            await client.disconnect()
            assert stopped.is_set()
            assert worker is not None
            assert not worker.is_alive()
            assert client._loop_thread is None
            assert client._worker is None
        finally:
            stopped.set()
            if worker is not None:
                worker.join(timeout=1)


@pytest.mark.asyncio
async def test_concurrent_startup_and_reconnect_readers_share_one_transport() -> None:
    client = _make_client()
    transport = _mock_transport(auto_connect=False)
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", return_value=transport) as factory:
        try:
            readers = [asyncio.create_task(client.connect()) for _ in range(4)]
            assert await asyncio.to_thread(transport.entered.wait, 1)
            worker = client._loop_thread
            factory.assert_called_once()
            transport.on_connect(transport, None, None, FakeReasonCode(0), None)
            await asyncio.gather(*readers)
            transport.on_disconnect(transport, None, None, FakeReasonCode(1), None)
            readers = [asyncio.create_task(client.connect()) for _ in range(4)]
            await asyncio.sleep(0.02)
            factory.assert_called_once()
            assert client._loop_thread is worker
            assert worker is not None
            assert worker.is_alive()
            transport.on_connect(transport, None, None, FakeReasonCode(0), None)
            await asyncio.gather(*readers)
        finally:
            await client.disconnect()


@pytest.mark.asyncio
async def test_repeated_timeouts_keep_the_reconnecting_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client()
    transport = _mock_transport()
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", return_value=transport) as factory:
        await client.connect()
        worker = client._loop_thread
        transport.on_disconnect(transport, None, None, FakeReasonCode(1), None)
        monkeypatch.setattr("mcp_venus_os.mqtt_client.CONNECT_WAIT_STEPS", 2)
        monkeypatch.setattr("mcp_venus_os.mqtt_client.CONNECT_POLL_S", 0.001)
        try:
            for _ in range(2):
                results = await asyncio.gather(
                    *(client.connect() for _ in range(3)), return_exceptions=True
                )
                assert all(isinstance(result, ConnectionTimeoutError) for result in results)
            factory.assert_called_once()
            transport.disconnect.assert_not_called()
            assert client._loop_thread is worker
            transport.on_connect(transport, None, None, FakeReasonCode(0), None)
            await client.connect()
        finally:
            await client.disconnect()


def test_retired_callbacks_and_queued_messages_cannot_change_current_state() -> None:
    client = _make_client()
    retired = _callback_transport(client)
    topic = f"{PREFIX}/battery/0/Soc"
    client._on_message(retired, None, _raw_msg(topic, b"11"))
    current = Mock()
    client.client = cast(mqtt.Client, current)
    client._connected = True
    client._on_disconnect(retired, None, None, cast(ReasonCode, FakeReasonCode(1)), None)
    assert client._connected
    client._on_connect(retired, None, None, cast(ReasonCode, FakeReasonCode(0)), None)
    client._on_message(retired, None, _raw_msg(topic, b"22"))
    client._drain_inbox()
    assert client.read_path("battery", 0, "Soc") is None
    cast(Mock, retired).publish.assert_not_called()
    current.publish.assert_not_called()
    _feed(client, topic, b"33")
    client._on_message(retired, None, _raw_msg(topic, b""))
    client._drain_inbox()
    cached = client.read_path("battery", 0, "Soc")
    assert cached is not None
    assert cached[0] == 33
    client.client = None
    client._connected = False
    client._on_connect(current, None, None, cast(ReasonCode, FakeReasonCode(0)), None)
    client._on_message(current, None, _raw_msg(topic, b"44"))
    client._drain_inbox()
    assert not client._connected
    cached = client.read_path("battery", 0, "Soc")
    assert cached is not None
    assert cached[0] == 33


@pytest.mark.asyncio
async def test_dead_network_loop_is_retired_before_retry() -> None:
    client = _make_client()
    first, second = _mock_transport(), _mock_transport()
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", side_effect=[first, second]) as factory:
        try:
            await client.connect()
            old_loop, old_worker = client._loop_thread, client._worker
            first.stopped.set()
            assert old_loop is not None
            await asyncio.to_thread(old_loop.join, 1)
            assert not client._connected
            await client.connect()
            assert factory.call_count == 2
            assert client.client is second
            assert old_worker is not None
            assert not old_worker.is_alive()
            assert not old_loop.is_alive()
        finally:
            await client.disconnect()


@pytest.mark.asyncio
async def test_initial_network_failure_can_retry_without_orphan_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mcp_venus_os.mqtt_client.CONNECT_WAIT_STEPS", 5)
    monkeypatch.setattr("mcp_venus_os.mqtt_client.CONNECT_POLL_S", 0.01)
    client = _make_client()
    first, second = _mock_transport(), _mock_transport()
    first.loop_forever.side_effect = OSError("synthetic connection failure")
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", side_effect=[first, second]) as factory:
        try:
            with pytest.raises(ConnectionTimeoutError):
                await client.connect()
            old_worker = client._worker
            await client.connect()
            assert factory.call_count == 2
            assert old_worker is not None
            assert not old_worker.is_alive()
            first.disconnect.assert_called_once()
        finally:
            await client.disconnect()


@pytest.mark.asyncio
async def test_disconnect_full_inbox_is_bounded_and_keeps_live_worker_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mcp_venus_os.mqtt_client.INBOX_MAXSIZE", 1)
    monkeypatch.setattr("mcp_venus_os.mqtt_client.WORKER_JOIN_TIMEOUT_S", 0.02)
    monkeypatch.setattr("mcp_venus_os.mqtt_client.NETWORK_JOIN_TIMEOUT_S", 0.02)
    client = _make_client()
    first, second = _mock_transport(), _mock_transport()
    entered, release = threading.Event(), threading.Event()

    def slow_callback(payload: Payload) -> None:
        entered.set()
        release.wait(timeout=2)

    client.subscribe(f"{PREFIX}/#", slow_callback)
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", side_effect=[first, second]) as factory:
        try:
            await client.connect()
            client._on_message(first, None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"1"))
            assert await asyncio.to_thread(entered.wait, 1)
            client._on_message(first, None, _raw_msg(f"{PREFIX}/battery/0/Soc", b"2"))
            assert client._inbox.full()
            worker = client._worker
            await asyncio.wait_for(client.disconnect(), timeout=0.5)
            assert worker is not None
            assert worker.is_alive()
            assert client._worker is worker
            assert client.client is first
            with pytest.raises(NotConnectedError):
                await asyncio.wait_for(client.connect(), timeout=0.5)
            factory.assert_called_once()
            release.set()
            await asyncio.to_thread(worker.join, 1)
            await client.disconnect()
            assert client.client is None
            assert client._worker is None
            assert client._loop_thread is None
            await client.connect()
            assert factory.call_count == 2
            cached = client.read_path("battery", 0, "Soc")
            assert cached is not None
            assert cached[0] == 1
        finally:
            release.set()
            await client.disconnect()


@pytest.mark.asyncio
async def test_disconnect_retires_pending_connection_without_replacement() -> None:
    client = _make_client()
    transport = _mock_transport(auto_connect=False)
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", return_value=transport) as factory:
        reader = asyncio.create_task(client.connect())
        assert await asyncio.to_thread(transport.entered.wait, 1)
        await client.disconnect()
        with pytest.raises(NotConnectedError):
            await reader
        factory.assert_called_once()
        assert client.client is None
        assert client._loop_thread is None


@pytest.mark.asyncio
async def test_cancelled_reader_leaves_one_owned_reconnect_loop() -> None:
    client = _make_client()
    transport = _mock_transport(auto_connect=False)
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", return_value=transport) as factory:
        try:
            reader = asyncio.create_task(client.connect())
            assert await asyncio.to_thread(transport.entered.wait, 1)
            reader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader
            transport.on_connect(transport, None, None, FakeReasonCode(0), None)
            await client.connect()
            factory.assert_called_once()
        finally:
            await client.disconnect()


@pytest.mark.asyncio
async def test_slow_network_shutdown_cannot_spawn_same_id_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mcp_venus_os.mqtt_client.NETWORK_JOIN_TIMEOUT_S", 0.01)
    client = _make_client()
    transport = _mock_transport()
    transport.disconnect.side_effect = None
    with patch("mcp_venus_os.mqtt_client.mqtt.Client", return_value=transport) as factory:
        try:
            await client.connect()
            network = client._loop_thread
            await asyncio.wait_for(client.disconnect(), timeout=0.5)
            assert network is not None
            assert network.is_alive()
            assert client._loop_thread is network
            assert client.client is transport
            with pytest.raises(NotConnectedError):
                await asyncio.wait_for(client.connect(), timeout=0.5)
            factory.assert_called_once()
        finally:
            transport.stopped.set()
            await client.disconnect()
        assert client.client is None
        assert client._loop_thread is None


def _connected_feed_client() -> tuple[MQTTClient, Mock]:
    client = _make_client()
    transport = Mock()
    transport.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    client.client = cast(mqtt.Client, transport)
    client._on_connect(
        client.client, None, None, cast(ReasonCode, FakeReasonCode(0)), cast(Properties, Mock())
    )
    return client, transport


def test_broker_filters_preserve_47_services_without_nested_noise() -> None:
    """A full publish must not fill the receiver with unused deep settings."""
    from mcp_venus_os.telemetry import DISCOVERY_PATHS

    client, transport = _connected_feed_client()
    filters = [call.args[0] for call in transport.subscribe.call_args_list]
    internal = (
        "adc",
        "digitalinputs",
        "ev",
        "evcharger",
        "fronius",
        "hub4",
        "logger",
        "modbusclient",
        "modbustcp",
        "packageManager",
        "platform",
        "settings",
        "shelly",
        "system",
        "pump",
        "tank",
        "battery",
        "solarcharger",
        "pvinverter",
        "grid",
        "vebus",
    )
    devices = [(name, 0) for name in internal] + [("acload", n) for n in range(26)]
    topics = [
        f"{PREFIX}/{name}/{instance}/"
        + DISCOVERY_PATHS.get(name, "Mgmt/ProcessName").replace("+", "1")
        for name, instance in devices
    ]
    topics += [f"{PREFIX}/settings/0/Settings/History/Entries/{n}" for n in range(10_000)]
    delivered = [
        topic for topic in topics if any(mqtt.topic_matches_sub(f, topic) for f in filters)
    ]
    assert len(delivered) == 47
    assert sum(len(topic) + 100 for topic in delivered) < 16_384
    for topic in delivered:
        _feed(client, topic, b'{"value":"synthetic-service"}')
    assert {(d["device_type"], d["instance"]) for d in client.list_devices()} == set(devices)
    _feed(client, delivered[0], b"")
    assert len(client.list_devices()) == 46


def test_filters_cover_all_consumed_fallbacks_and_deep_contracts(
    hardware_contracts: list[HardwareWriteContract],
) -> None:
    from mcp_venus_os.telemetry import READ_PATHS, contract_topics

    client = _make_client()
    for contract in hardware_contracts:
        contract.identity[0].path = "Firmware/Installed/Version"
    client._contracts = hardware_contracts
    filters = client._base_subscriptions()
    topics = contract_topics(PREFIX, hardware_contracts)
    for family, fields in READ_PATHS.items():
        topics.update(
            f"{PREFIX}/{family}/789/{path}" for paths in fields.values() for path in paths
        )
    assert all(any(mqtt.topic_matches_sub(f, topic) for f in filters) for topic in topics)
    assert any("/platform/0/Firmware/Installed/Version" in f for f in filters)
    assert not any(
        mqtt.topic_matches_sub(f, f"{PREFIX}/settings/0/Settings/History/X") for f in filters
    )
    assert not any(
        mqtt.topic_matches_sub(f, "N/other/vebus/256/Dc/0/MaxChargeCurrent") for f in filters
    )


def test_exact_subscriptions_do_not_duplicate_owned_broker_filters(
    hardware_contracts: list[HardwareWriteContract],
) -> None:
    client, transport = _connected_feed_client()
    probe = hardware_contracts[0].identity[0]
    probe.device_type, probe.instance, probe.path = "battery", 512, "Dc/0/Voltage"
    client._contracts = hardware_contracts[:1]
    topic = f"{PREFIX}/battery/512/Dc/0/Voltage"
    assert sum(mqtt.topic_matches_sub(f, topic) for f in client._base_subscriptions()) == 1
    transport.subscribe.reset_mock()
    callback = Mock()
    client.subscribe(topic, callback)
    transport.subscribe.assert_not_called()
    _feed(client, topic, b'{"value":52}')
    callback.assert_called_once_with(52)
    client._on_connect(
        cast(mqtt.Client, transport),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(0)),
        cast(Properties, Mock()),
    )
    assert (
        sum(
            mqtt.topic_matches_sub(call.args[0], topic)
            for call in transport.subscribe.call_args_list
        )
        == 1
    )
    client.unsubscribe(topic, callback)
    transport.unsubscribe.assert_not_called()


def test_maintenance_keeps_constant_values_fresh_without_full_reflood() -> None:
    client, transport = _connected_feed_client()
    topics = [f"{PREFIX}/battery/512/Soc", f"{PREFIX}/battery/512/Dc/0/Power"]
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=0.0):
        for topic in topics:
            _feed(client, topic, b'{"value":55}')
    client._maintain_read_feed(0.0)
    transport.publish.reset_mock()
    for now in (30.0, 60.0, 90.0):

        def reply(topic: str, payload: str, *, retain: bool) -> Mock:
            assert topic.startswith("R/")
            assert not retain
            if topic.endswith("/keepalive"):
                assert payload == '{"keepalive-options":["suppress-republish"]}'
            else:
                assert payload == ""
                _feed(client, "N/" + topic[2:], b'{"value":55}')
            return Mock(rc=mqtt.MQTT_ERR_SUCCESS)

        transport.publish.side_effect = reply
        with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=now):
            client._maintain_read_feed(now)
            assert client.read_path("battery", 512, "Soc") == (55, 0.0)
    assert transport.publish.call_count == 9
    assert all(
        call.args[0] != f"R/{PORTAL}/system/0/Serial" for call in transport.publish.call_args_list
    )


def test_no_reply_does_not_forge_freshness_and_serial_never_refloods() -> None:
    client, transport = _connected_feed_client()
    serial = f"{PREFIX}/system/0/Serial"
    client.subscribe(serial, _noop)
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=0.0):
        _feed(client, serial, b'{"value":"synthetic-portal"}')
        _feed(client, f"{PREFIX}/battery/512/Soc", b'{"value":55}')
    client._maintain_read_feed(0.0)
    transport.publish.reset_mock()
    for now in (30.0, 60.0, 90.0):
        client._maintain_read_feed(now)
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=90.0):
        assert client.read_path("battery", 512, "Soc") == (55, 90.0)
    serial_calls = [
        call for call in transport.publish.call_args_list if call.args[0] == "R/" + serial[2:]
    ]
    assert len(serial_calls) == 3
    assert all(
        call.args[1] == '{"keepalive-options":["suppress-republish"]}' for call in serial_calls
    )
    assert all(
        "+" not in call.args[0] and "#" not in call.args[0]
        for call in transport.publish.call_args_list
    )


def test_contract_serial_requires_live_suppressed_read_after_retained_replay(
    hardware_contracts: list[HardwareWriteContract],
) -> None:
    client, transport = _connected_feed_client()
    probe = hardware_contracts[0].identity[0]
    probe.device_type, probe.instance, probe.path = "system", 0, "Serial"
    client._contracts = hardware_contracts[:1]
    serial = f"{PREFIX}/system/0/Serial"
    retained = _raw_msg(serial, b'{"value":"synthetic-portal"}')
    retained.retain = True
    client._on_message(cast(mqtt.Client, transport), None, retained)
    client._drain_inbox()
    assert client.read_path("system", 0, "Serial") is None
    assert client.read_path_since("system", 0, "Serial", 0.0) is None
    assert serial in client._refresh_candidates()
    client._maintain_read_feed(0.0)
    transport.publish.reset_mock()

    def flashmq_reply(topic: str, payload: str, *, retain: bool) -> Mock:
        assert not retain
        # Both the keepalive and legacy Serial alias suppress publish_all.
        assert json.loads(payload) == {"keepalive-options": ["suppress-republish"]}
        if topic == "R/" + serial[2:]:
            _feed(client, serial, b'{"value":"synthetic-portal"}')
        return Mock(rc=mqtt.MQTT_ERR_SUCCESS)

    transport.publish.side_effect = flashmq_reply
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=30.0):
        client._maintain_read_feed(30.0)
        assert client.read_path_since("system", 0, "Serial", 30.0) == ("synthetic-portal", 0.0)
    assert transport.publish.call_count == 2
    # A later retained replay cannot refresh the live reply's receipt time.
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=60.0):
        client._on_message(cast(mqtt.Client, transport), None, retained)
        client._drain_inbox()
        assert client.read_path("system", 0, "Serial") == ("synthetic-portal", 30.0)
    _feed(client, serial, b"")
    assert client.read_path("system", 0, "Serial") is None
    assert serial not in client._refresh_candidates()


def test_refresh_rotates_large_catalog_without_discovery_only_reads() -> None:
    from mcp_venus_os.mqtt_client import MAX_REFRESH_TOPICS

    client, transport = _connected_feed_client()
    topics = {f"{PREFIX}/battery/{instance}/Soc" for instance in range(MAX_REFRESH_TOPICS + 20)}
    for topic in topics:
        _feed(client, topic, b'{"value":55}')
    _feed(client, f"{PREFIX}/settings/0/Settings/Vrmlogger/LogInterval", b'{"value":60}')
    client._maintain_read_feed(0.0)
    transport.publish.reset_mock()
    for cycle in (30.0, 60.0):
        for batch in range(64):
            client._maintain_read_feed(cycle + batch * 0.25)
    read_topics = {
        "N/" + call.args[0][2:]
        for call in transport.publish.call_args_list
        if not call.args[0].endswith("/keepalive")
    }
    assert read_topics == topics


def test_refresh_batches_are_bounded_and_dynamic_removal_stops_reads() -> None:
    from mcp_venus_os.mqtt_client import MAX_REFRESH_TOPICS, REFRESH_BATCH_SIZE

    client, transport = _connected_feed_client()
    for instance in range(MAX_REFRESH_TOPICS + 20):
        _feed(client, f"{PREFIX}/battery/{instance}/Soc", b'{"value":55}')
    custom = f"{PREFIX}/custom/0/Deep/Value"
    client.subscribe(custom, _noop)
    _feed(client, custom, b'{"value":1}')
    client._maintain_read_feed(0.0)
    transport.publish.reset_mock()
    client._maintain_read_feed(30.0)
    assert transport.publish.call_count == REFRESH_BATCH_SIZE + 1
    assert len(client._pending_refresh) == MAX_REFRESH_TOPICS - REFRESH_BATCH_SIZE
    client._pending_refresh.appendleft(custom)
    client.unsubscribe(custom, _noop)
    transport.unsubscribe.assert_called_once_with(custom)
    client._maintain_read_feed(30.25)
    assert not any(call.args[0] == "R/" + custom[2:] for call in transport.publish.call_args_list)
    # Deleted data must not be resurrected by a queued refresh request.
    deleted = client._pending_refresh[0]
    _feed(client, deleted, b"")
    transport.publish.reset_mock()
    client._maintain_read_feed(30.5)
    assert not any(call.args[0] == "R/" + deleted[2:] for call in transport.publish.call_args_list)


def test_maintenance_retries_failures_and_stops_with_owned_worker() -> None:
    client, transport = _connected_feed_client()
    _feed(client, f"{PREFIX}/battery/512/Soc", b'{"value":55}')
    client._maintain_read_feed(0.0)
    transport.publish.reset_mock()
    transport.publish.return_value.rc = mqtt.MQTT_ERR_NO_CONN
    client._maintain_read_feed(30.0)
    assert len(client._pending_refresh) == 1
    transport.publish.side_effect = RuntimeError("synthetic transport failure")
    client._maintain_read_feed(31.0)
    assert len(client._pending_refresh) == 1
    transport.publish.side_effect = None
    transport.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    client._maintain_read_feed(32.0)
    assert not client._pending_refresh
    transport.publish.reset_mock()
    client._worker_stop.set()
    client._maintain_read_feed(100.0)
    transport.publish.assert_not_called()


def test_reconnect_resubscribes_explicit_filters_and_resets_read_schedule() -> None:
    client, transport = _connected_feed_client()
    explicit = f"{PREFIX}/custom/0/Deep/Value"
    client.subscribe(explicit, _noop)
    client._maintain_read_feed(0.0)
    client._pending_refresh.append(explicit)
    transport.reset_mock()
    client._on_connect(
        cast(mqtt.Client, transport),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(0)),
        cast(Properties, Mock()),
    )
    assert explicit in [call.args[0] for call in transport.subscribe.call_args_list]
    client._maintain_read_feed(29.0)
    assert not client._pending_refresh
    transport.publish.reset_mock()
    client._maintain_read_feed(30.0)
    transport.publish.assert_not_called()
    client.unsubscribe(explicit, _noop)
    transport.reset_mock()
    client._on_connect(
        cast(mqtt.Client, transport),
        None,
        None,
        cast(ReasonCode, FakeReasonCode(0)),
        cast(Properties, Mock()),
    )
    assert explicit not in [call.args[0] for call in transport.subscribe.call_args_list]
