"""Exercise diagnostic callbacks through real Paho writes, without a network loop."""

import json
import threading
from collections import deque
from collections.abc import Generator
from typing import cast
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt
import pytest
from paho.mqtt.enums import CallbackAPIVersion, _ConnectionState
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from mcp_venus_os.config import MQTTConfig, ServerConfig
from mcp_venus_os.mqtt_client import MQTTClient

SECRET = "never-log-this-portal-password-topic-payload"


class ScriptedSocket:
    """A socket whose send() can block, accept a prefix, or accept all bytes."""

    def __init__(self, writes: tuple[int | Exception, ...] = ()) -> None:
        self.writes = deque(writes)
        self.accepted = bytearray()
        self.send_calls = 0
        self.closed = False
        self.send_queue_bytes = 7

    def send(self, buffer: bytes) -> int:
        assert not self.closed
        self.send_calls += 1
        result = self.writes.popleft() if self.writes else len(buffer)
        if isinstance(result, Exception):
            raise result
        assert 0 <= result <= len(buffer)
        self.accepted.extend(buffer[:result])
        return result

    def recv(self, buffer_size: int) -> bytes:
        raise AssertionError

    def fileno(self) -> int:
        return -1 if self.closed else 101

    def setblocking(self, flag: bool) -> None:
        raise AssertionError

    def close(self) -> None:
        self.closed = True

    def __repr__(self) -> str:
        return SECRET


def _connected(owner: MQTTClient, transport: mqtt.Client) -> None:
    transport._state = _ConnectionState.MQTT_CS_CONNECTED
    with patch.object(transport, "subscribe"), patch.object(transport, "publish"):
        owner._on_connect(
            transport, None, None, ReasonCode(PacketTypes.CONNACK), cast(Properties, Mock())
        )


def _open(transport: mqtt.Client, sock: ScriptedSocket) -> None:
    transport._sock = sock
    transport._call_socket_open(sock)


def _disconnect(transport: mqtt.Client) -> None:
    transport._do_on_disconnect(packet_from_broker=False, v1_rc=mqtt.MQTT_ERR_KEEPALIVE)


def _snapshots(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        json.loads(record.getMessage().split("mqtt_diagnostics=", 1)[1])
        for record in caplog.records
        if "mqtt_diagnostics=" in record.getMessage()
    ]


def _events(snapshot: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], snapshot["transport_events"])


@pytest.fixture
def session() -> Generator[tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock], None, None]:
    config = ServerConfig(
        mqtt=MQTTConfig(host="localhost", portal_id=SECRET, password=SECRET, client_id=SECRET)
    )
    with patch("mcp_venus_os.mqtt_client.get_config", return_value=config):
        owner = MQTTClient()
    transport = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    # Paho's native threaded mode enqueues on the caller and writes on its loop.
    # An unstarted thread emulates that queueing rule without creating a worker.
    transport._thread = threading.Thread()
    sock = ScriptedSocket()

    def metadata(candidate: object | None) -> dict[str, int | str]:
        assert isinstance(candidate, ScriptedSocket)
        assert not candidate.closed, "metadata must be frozen before the socket closes"
        return {"status": "ok", "send_queue_bytes": candidate.send_queue_bytes}

    with patch("mcp_venus_os.mqtt_client.sample_socket", side_effect=metadata) as sampler:
        with (
            patch("mcp_venus_os.mqtt_client.mqtt.Client", return_value=transport),
            patch.object(owner, "_start_worker"),
            patch.object(transport, "loop_start", return_value=mqtt.MQTT_ERR_SUCCESS),
        ):
            # Use production registration so a missing socket callback breaks tests.
            owner._start_transport()
        _open(transport, sock)
        _connected(owner, transport)
        try:
            yield owner, transport, sock, sampler
        finally:
            owner._stopping = True
            transport._sock_close()


@pytest.mark.parametrize(
    ("writes", "accepted", "drained"),
    [
        ((BlockingIOError(),), b"", False),
        ((1, BlockingIOError()), b"\xc0", False),
        ((1, 1), b"\xc0\x00", True),
    ],
    ids=["blocked", "partial", "full"],
)
def test_ping_attempt_is_not_output_drain(
    session: tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock],
    caplog: pytest.LogCaptureFixture,
    writes: tuple[int | Exception, ...],
    accepted: bytes,
    drained: bool,
) -> None:
    owner, transport, sock, sampler = session
    sock.writes.extend(writes)
    queue_at_log: list[bool] = []

    def logged(client: mqtt.Client, userdata: object, level: int, message: str) -> None:
        if message == "Sending PINGREQ":
            queue_at_log.append(client.want_write())
        owner._on_log(client, userdata, level, message)

    transport.on_log = logged
    assert transport._send_pingreq() == mqtt.MQTT_ERR_SUCCESS
    assert queue_at_log == [False]  # Paho logs before it enqueues even one byte.
    assert transport.want_write()
    assert sock.send_calls == 0
    assert sampler.call_count == 2  # socket_open and attempt; no premature drain.

    assert transport.loop_write() == mqtt.MQTT_ERR_SUCCESS
    assert bytes(sock.accepted) == accepted
    assert transport.want_write() is not drained
    _disconnect(transport)
    snapshot = _snapshots(caplog)[0]
    expected = ["socket_open", "pingreq_attempt"]
    if drained:
        expected.append("output_drained_after_pingreq")
    assert [event["event"] for event in _events(snapshot)] == expected
    assert snapshot["pingreq_attempts"] == 1
    assert snapshot["pingresp_received"] == 0


def test_ping_bytes_can_finish_before_the_whole_output_queue_drains(
    session: tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, transport, sock, sampler = session
    transport._send_pingreq()
    transport.publish(f"secret/{SECRET}", SECRET)
    sock.writes.extend((2, BlockingIOError()))
    transport.loop_write()
    assert bytes(sock.accepted) == b"\xc0\x00"
    assert transport.want_write()
    assert sampler.call_count == 2
    transport.loop_write()
    assert not transport.want_write()
    assert sampler.call_count == 3
    # Unrelated later publish drains must not be attributed to the old PINGREQ.
    transport.publish("other", SECRET)
    transport.loop_write()
    assert sampler.call_count == 3
    _disconnect(transport)
    assert [event["event"] for event in _events(_snapshots(caplog)[0])] == [
        "socket_open",
        "pingreq_attempt",
        "output_drained_after_pingreq",
    ]


def test_closing_unregister_is_not_a_drain_even_with_an_empty_queue(
    session: tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner, transport, sock, sampler = session
    transport._send_pingreq()
    # Isolate the close guard: no pending output remains, but a PING attempt and
    # Paho's write registration do. An empty queue alone cannot prove a write.
    transport._out_packet.clear()
    observed_close_state: list[tuple[bool, bool, bool]] = []

    def unregister(client: mqtt.Client, userdata: object, candidate: object) -> None:
        observed_close_state.append((client.socket() is None, sock.closed, client.want_write()))
        owner._on_socket_unregister_write(client, userdata, candidate)

    transport.on_socket_unregister_write = unregister
    transport._sock_close()
    assert observed_close_state == [(True, False, False)]
    assert sock.closed
    assert sampler.call_count == 3
    _disconnect(transport)
    assert [event["event"] for event in _events(_snapshots(caplog)[0])] == [
        "socket_open",
        "pingreq_attempt",
        "socket_close",
    ]


def test_close_metadata_is_frozen_and_duplicate_disconnect_does_not_resample(
    session: tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, transport, sock, sampler = session
    sock.send_queue_bytes = 901
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=100.0):
        transport._sock_close()
    count_at_close = sampler.call_count
    sock.send_queue_bytes = 0
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=105.0):
        _disconnect(transport)
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=108.0):
        _disconnect(transport)
    first, second = _snapshots(caplog)
    assert sampler.call_count == count_at_close
    assert _events(first)[-1] == {
        "event": "socket_close",
        "socket_generation": 1,
        "socket": {"status": "ok", "send_queue_bytes": 901},
        "age_s": 5.0,
    }
    assert not first["transport_events_repeated"]
    assert second["transport_events_repeated"]
    assert _events(second) == []
    assert second["duplicate_in_epoch"]
    assert second["socket_generation"] == first["socket_generation"] == 1


def test_socket_generation_advances_even_when_next_connection_never_gets_connack(
    session: tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner, transport, old_socket, sampler = session
    transport._send_pingreq()
    transport._sock_close()
    _disconnect(transport)
    new_socket = ScriptedSocket()
    _open(transport, new_socket)
    count_after_open = sampler.call_count
    # Late callbacks for the first socket must neither close the new socket's
    # diagnostic identity nor satisfy its old pending PINGREQ.
    owner._on_socket_open(transport, None, old_socket)
    owner._on_socket_close(transport, None, old_socket)
    owner._on_socket_unregister_write(transport, None, old_socket)
    assert sampler.call_count == count_after_open
    transport._sock_close()
    _disconnect(transport)
    first, second = _snapshots(caplog)
    assert first["connection_epoch"] == second["connection_epoch"] == 1
    assert first["socket_generation"] == 1
    assert second["socket_generation"] == 2
    assert not second["transport_events_repeated"]
    assert [event["event"] for event in _events(second)] == ["socket_open", "socket_close"]
    assert all(event["socket_generation"] == 2 for event in _events(second))


@pytest.mark.parametrize("ignored", ["retired_client", "stopping"])
def test_retired_or_stopping_callbacks_do_not_sample_or_change_diagnostics(
    session: tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock],
    caplog: pytest.LogCaptureFixture,
    ignored: str,
) -> None:
    owner, transport, sock, sampler = session
    if ignored == "retired_client":
        candidate = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    else:
        candidate = transport
        owner._stopping = True
    count_before = sampler.call_count
    owner._on_log(candidate, None, mqtt.MQTT_LOG_DEBUG, "Sending PINGREQ")
    owner._on_log(candidate, None, mqtt.MQTT_LOG_DEBUG, "Received PINGRESP")
    owner._on_socket_open(candidate, None, sock)
    owner._on_socket_unregister_write(candidate, None, sock)
    owner._on_socket_close(candidate, None, sock)
    owner._on_disconnect(candidate, None, None, ReasonCode(PacketTypes.DISCONNECT), None)
    assert sampler.call_count == count_before
    assert _snapshots(caplog) == []
    owner._stopping = False
    _disconnect(transport)
    snapshot = _snapshots(caplog)[0]
    assert snapshot["socket_generation"] == 1
    assert snapshot["pingreq_attempts"] == snapshot["pingresp_received"] == 0
    assert [event["event"] for event in _events(snapshot)] == ["socket_open"]


def test_event_ring_is_bounded_and_does_not_capture_secrets(
    session: tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, transport, _, _ = session
    for _ in range(40):
        transport._send_pingreq()
        transport.loop_write()
        assert transport._handle_pingresp() == mqtt.MQTT_ERR_SUCCESS
        transport._easy_log(mqtt.MQTT_LOG_DEBUG, "Received PUBLISH %s", SECRET)
        transport._easy_log(mqtt.MQTT_LOG_DEBUG, "Sending PINGREQ %s", SECRET)
    transport.publish(f"private/{SECRET}", SECRET)
    transport.loop_write()
    transport._sock_close()
    _disconnect(transport)
    snapshot = _snapshots(caplog)[0]
    events = _events(snapshot)
    assert len(events) == 12
    assert events[-1]["event"] == "socket_close"
    assert "socket_open" not in [event["event"] for event in events]
    assert snapshot["pingreq_attempts"] == snapshot["pingresp_received"] == 40
    assert all(set(event) == {"event", "socket_generation", "socket", "age_s"} for event in events)
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps(snapshot)
    assert len(json.dumps(snapshot)) < 6000


def test_publish_traffic_does_not_invoke_the_socket_sampler(
    session: tuple[MQTTClient, mqtt.Client, ScriptedSocket, Mock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner, transport, _, sampler = session
    sampler.reset_mock()
    for _ in range(200):
        transport.publish(f"private/{SECRET}", SECRET)
        transport.loop_write()
        incoming = mqtt.MQTTMessage(topic=f"N/{SECRET}/battery/1/Soc".encode())
        incoming.payload = SECRET.encode()
        owner._on_message(transport, None, incoming)
    sampler.assert_not_called()
    _disconnect(transport)
    snapshot = _snapshots(caplog)[0]
    assert snapshot["inbox_depth"] == 200
    assert [event["event"] for event in _events(snapshot)] == ["socket_open"]
    assert SECRET not in caplog.text
