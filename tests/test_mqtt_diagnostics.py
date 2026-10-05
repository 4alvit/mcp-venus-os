"""Exercise metadata diagnostics through the pinned Paho packet callbacks."""

import json
import queue
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


def _owner() -> tuple[MQTTClient, mqtt.Client]:
    config = ServerConfig(
        mqtt=MQTTConfig(host="localhost", portal_id="private-portal", password="private-password")
    )
    with patch("mcp_venus_os.mqtt_client.get_config", return_value=config):
        owner = MQTTClient()
    transport = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    owner.client = transport
    transport.on_log = owner._on_log
    transport.on_disconnect = owner._on_disconnect
    _connected(owner, transport)
    return owner, transport


def _connected(owner: MQTTClient, transport: mqtt.Client) -> None:
    with patch.object(transport, "subscribe"), patch.object(transport, "publish"):
        owner._on_connect(
            transport, None, None, ReasonCode(PacketTypes.CONNACK), cast(Properties, Mock())
        )


def _ping(transport: mqtt.Client) -> None:
    # Paho emits its real public on_log event before queueing the control packet.
    with patch.object(transport, "_send_simple_command", return_value=mqtt.MQTT_ERR_SUCCESS):
        assert transport._send_pingreq() == mqtt.MQTT_ERR_SUCCESS


def _disconnect(transport: mqtt.Client) -> None:
    transport._do_on_disconnect(packet_from_broker=False, v1_rc=mqtt.MQTT_ERR_KEEPALIVE)


def _snapshots(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        cast(dict[str, object], json.loads(record.getMessage().split("mqtt_diagnostics=", 1)[1]))
        for record in caplog.records
        if "mqtt_diagnostics=" in record.getMessage()
    ]


def test_real_paho_control_events_produce_only_bounded_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=100):
        owner, transport = _owner()
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=130):
        _ping(transport)
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=131):
        transport._in_packet["remaining_length"] = 0
        assert transport._handle_pingresp() == mqtt.MQTT_ERR_SUCCESS
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=140):
        msg = mqtt.MQTTMessage(topic=b"N/private-portal/private-topic")
        msg.payload = b"private-payload"
        owner._on_message(transport, None, msg)
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=145):
        _disconnect(transport)
    assert _snapshots(caplog) == [
        {
            "connection_epoch": 1,
            "disconnect_callback": 1,
            "duplicate_in_epoch": False,
            "session_age_s": 45.0,
            "notification_age_s": 5.0,
            "pingreq_attempt_age_s": 15.0,
            "pingresp_age_s": 14.0,
            "pingreq_attempts": 1,
            "pingresp_received": 1,
            "inbox_depth": 1,
            "inbox_dropped": 0,
        }
    ]
    assert len(caplog.text) < 1000
    assert "private-" not in caplog.text
    # Receipt age is independent from decoder progress; diagnostics don't drain
    # or reinterpret a queued message and never freshen the read cache.
    assert owner._cache == {}
    assert owner._inbox.get_nowait() == (transport, msg, 140)


def test_unrelated_paho_log_strings_are_not_stored_or_forwarded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner, transport = _owner()
    before = dict(vars(owner))
    transport._easy_log(
        mqtt.MQTT_LOG_DEBUG, "Received PUBLISH '%s': %s", "secret-topic", "secret-data"
    )
    transport._easy_log(mqtt.MQTT_LOG_ERR, "secret-credentials %s", "private-password")
    transport._easy_log(mqtt.MQTT_LOG_DEBUG, "Sending PINGREQ with secret suffix")
    assert vars(owner) == before
    assert not caplog.records
    assert transport._logger is None  # No global or Paho debug logger is enabled.


@pytest.mark.parametrize("state", ["retired", "stopping", "disconnected"])
def test_control_metadata_ignores_unowned_or_inactive_sessions(
    state: str, caplog: pytest.LogCaptureFixture
) -> None:
    owner, transport = _owner()
    if state == "retired":
        owner.client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    elif state == "stopping":
        owner._stopping = True
    else:
        owner._connected = False
    _ping(transport)
    transport._in_packet["remaining_length"] = 0
    transport._handle_pingresp()
    assert owner._last_pingreq_at is None
    assert owner._last_pingresp_at is None
    assert owner._pingreq_attempts == owner._pingresp_received == 0
    if state != "disconnected":
        _disconnect(transport)
        assert not _snapshots(caplog)


def test_reconnect_resets_only_session_diagnostics(caplog: pytest.LogCaptureFixture) -> None:
    owner, transport = _owner()
    _ping(transport)
    _disconnect(transport)
    owner._inbox_dropped = 3
    caplog.clear()
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=200):
        _connected(owner, transport)
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=201):
        _disconnect(transport)
    snapshot = _snapshots(caplog)[0]
    assert snapshot["connection_epoch"] == 2
    assert snapshot["disconnect_callback"] == 1
    assert snapshot["duplicate_in_epoch"] is False
    assert snapshot["session_age_s"] == 1
    assert snapshot["notification_age_s"] is None
    assert snapshot["pingreq_attempt_age_s"] is None
    assert snapshot["pingresp_age_s"] is None
    assert snapshot["pingreq_attempts"] == snapshot["pingresp_received"] == 0
    assert snapshot["inbox_dropped"] == 0


def test_full_inbox_records_receipt_and_drop_without_blocking(
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner, transport = _owner()
    owner._inbox = queue.Queue(maxsize=1)
    msg = mqtt.MQTTMessage(topic=b"private-topic")
    msg.payload = b"private-payload"
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=100):
        owner._on_message(transport, None, msg)
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=101):
        owner._on_message(transport, None, msg)
    with patch("mcp_venus_os.mqtt_client.time.monotonic", return_value=110):
        _disconnect(transport)
    snapshot = _snapshots(caplog)[0]
    assert snapshot["notification_age_s"] == 9
    assert snapshot["inbox_depth"] == snapshot["inbox_dropped"] == 1
    assert "private-" not in caplog.text


def test_one_real_paho_keepalive_failure_can_emit_two_callbacks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner, transport = _owner()
    # Offline reproduction of Paho2.1's two keepalive checks. Only its fake
    # socket/timers are arranged here; production code never mutates them.
    transport._sock = Mock()
    transport._state = _ConnectionState.MQTT_CS_CONNECTED
    transport._keepalive = 30
    transport._last_msg_in = transport._last_msg_out = 0
    transport._ping_t = 1
    with patch("paho.mqtt.client.time_func", return_value=100):
        assert transport.loop_misc() == mqtt.MQTT_ERR_CONN_LOST
    snapshots = _snapshots(caplog)
    assert len(snapshots) == 2
    assert [s["connection_epoch"] for s in snapshots] == [1, 1]
    assert [s["disconnect_callback"] for s in snapshots] == [1, 2]
    assert [s["duplicate_in_epoch"] for s in snapshots] == [False, True]
    assert not owner._connected
    assert owner.client is transport
