"""MQTT client for the Venus OS MQTT gateway (read path)."""

import asyncio
import contextlib
import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.matcher import MQTTMatcher

from .capabilities import capability_subscriptions, is_capability_topic
from .config import MissingPortalIdError, get_config

logger = logging.getLogger(__name__)

# MQTT protocol keepalive (s): short enough that a broker drop is noticed fast,
# long enough to ride out brief load spikes between PINGREQs.
MQTT_PROTOCOL_KEEPALIVE_S = 30
# Bound on queued inbound messages; when full, new messages are dropped (the
# next publish of any topic refreshes the cache anyway).
INBOX_MAXSIZE = 50_000
# Minimum seconds between "inbox overflow" warnings.
DROP_LOG_INTERVAL_S = 10.0
# Yield after a bounded batch during full-tree refreshes. Sleeping after every
# message adds a scheduler delay to every cached value and makes bursts stale.
# queue.get() already blocks when empty, so idle connections do not spin.
INBOX_PROCESS_BATCH_SIZE = 64
INBOX_PROCESS_SLEEP_S = 0.0001
CONNECT_WAIT_STEPS = 50
CONNECT_POLL_S = 0.1
WORKER_JOIN_TIMEOUT_S = 2.0
NETWORK_JOIN_TIMEOUT_S = 5.0


class MQTTError(Exception):
    """Base exception for MQTT errors."""

    pass


class NotConnectedError(MQTTError):
    """Raised when MQTT is not connected."""

    pass


class ConnectionTimeoutError(MQTTError):
    """Raised when MQTT connection times out."""

    pass


# Type alias for MQTT callback payload
Payload = dict[str, Any] | list[Any] | str | int | float | bool | None


class MQTTClient:
    """MQTT client for Venus OS data streaming."""

    def __init__(self) -> None:
        self.config = get_config().mqtt
        self.client: mqtt.Client | None = None
        self._connected = False
        self._lifecycle_lock = asyncio.Lock()
        self._state_lock = threading.Lock()
        self._stopping = False
        self._worker_stop = threading.Event()
        self._callbacks: dict[str, list[Callable[[Payload], None]]] = {}
        # Paho's matcher has no type annotations in the pinned 2.1 release.
        self._callback_index = MQTTMatcher()  # type: ignore[no-untyped-call]
        self._callback_lock = threading.Lock()
        # Last value per topic, with monotonic receive time (read cache)
        self._cache: dict[str, tuple[Payload, float]] = {}
        # Inbound messages are decoded off paho's network thread: heavy work
        # inline in _loop starves _check_keepalive → broker drops the
        # connection every keepalive interval → full retained-tree re-flood.
        self._inbox: queue.Queue[tuple[mqtt.Client, mqtt.MQTTMessage, float] | None] = queue.Queue(
            maxsize=INBOX_MAXSIZE
        )
        self._worker: threading.Thread | None = None
        self._loop_thread: threading.Thread | None = None
        self._last_drop_log = 0.0

    @property
    def prefix(self) -> str:
        """Topic prefix for this portal, e.g. N/<portalId>."""
        return self.config.topic_prefix

    @property
    def write_prefix(self) -> str:
        """Write-topic prefix for this portal, e.g. W/<portalId>."""
        if not self.config.portal_id:
            raise MissingPortalIdError()
        return f"W/{self.config.portal_id}"

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,  # noqa: ANN401
        flags: Any,  # noqa: ANN401
        reason_code: mqtt.ReasonCode,  # type: ignore[name-defined]
        properties: mqtt.Properties,  # type: ignore[name-defined]
    ) -> None:
        """MQTT on_connect callback."""
        with self._state_lock:
            if client is not self.client or self._stopping:
                return
            self._connected = reason_code == 0
        if reason_code == 0:
            logger.info("Connected to MQTT broker at %s:%d", self.config.host, self.config.port)
            base = f"{self.prefix}/#"
            client.subscribe(base)
            logger.debug("Subscribed to %s", base)
            # Companion-service topics (inverter-control, dbus-pump, …)
            for pattern in capability_subscriptions():
                client.subscribe(pattern)
                logger.debug("Subscribed to %s", pattern)
            # FlashMQ has no retained item tree. Request it after subscriptions
            # on each connection; this is a read, not a control-value watchdog.
            client.publish(f"R/{self.config.portal_id}/keepalive", "", retain=False)
        else:
            logger.error("Failed to connect to MQTT broker: %s", reason_code)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,  # noqa: ANN401
        flags: Any,  # noqa: ANN401
        reason_code: mqtt.ReasonCode,  # type: ignore[name-defined]
        properties: mqtt.Properties,  # type: ignore[name-defined]
    ) -> None:
        """MQTT on_disconnect callback."""
        with self._state_lock:
            if client is not self.client or self._stopping:
                return
            self._connected = False
        logger.warning("Disconnected from MQTT broker: %s", reason_code)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,  # noqa: ANN401
        msg: mqtt.MQTTMessage,
    ) -> None:
        """MQTT on_message callback (paho network thread).

        Only enqueues: decoding here would hold the GIL in long stretches and
        starve paho's keepalive check.
        """
        try:
            # Capture receipt before queueing: decoder delay is part of the age
            # and cannot turn a pre-command message into a fresh write response.
            with self._state_lock:
                if client is not self.client or self._stopping:
                    return
                self._inbox.put_nowait((client, msg, time.monotonic()))
        except queue.Full:
            now = time.monotonic()
            if now - self._last_drop_log >= DROP_LOG_INTERVAL_S:
                logger.warning("MQTT inbox overflow, dropping messages")
                self._last_drop_log = now

    def _run_loop(self, client: mqtt.Client) -> None:
        """Own initial connection retries and reconnects in one network loop.

        The existing 5s select timeout remains below the protocol keepalive.
        """
        try:
            client.loop_forever(timeout=5.0, retry_first_connection=True)
        except Exception:
            logger.exception("MQTT network loop stopped")
        finally:
            with self._state_lock:
                if client is self.client:
                    self._connected = False

    def _drain_inbox(self) -> None:
        """Process all queued messages synchronously (tests, shutdown)."""
        while True:
            try:
                entry = self._inbox.get_nowait()
            except queue.Empty:
                return
            if entry is not None:  # skip stale shutdown sentinels
                self._handle_message(*entry)

    def _process_inbox(self) -> None:
        """Worker thread: decode messages and update the cache/callbacks."""
        processed = 0
        while not self._worker_stop.is_set():
            try:
                entry = self._inbox.get(timeout=0.25)
            except queue.Empty:
                continue
            if entry is None:  # shutdown sentinel
                return
            self._handle_message(*entry)
            processed += 1
            if processed >= INBOX_PROCESS_BATCH_SIZE:
                time.sleep(INBOX_PROCESS_SLEEP_S)
                processed = 0

    def _start_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker_stop.clear()
            self._worker = threading.Thread(
                target=self._process_inbox, name="mqtt-message-worker", daemon=True
            )
            self._worker.start()

    def _handle_message(
        self, client: mqtt.Client, msg: mqtt.MQTTMessage, received_at: float
    ) -> None:
        """Decode one message, update the cache, notify callbacks."""
        try:
            # An empty notification means the D-Bus item disappeared. Its former
            # identity/value must no longer authorize writes or appear in discovery.
            if not msg.payload:
                with self._state_lock:
                    if client is self.client and not self._stopping:
                        self._cache.pop(msg.topic, None)
                return
            payload = json.loads(msg.payload.decode())
            # Venus gateway wraps item values as {"value": X}; unwrap so the
            # cache (and every reader) sees plain scalars.
            if isinstance(payload, dict) and set(payload) == {"value"}:
                payload = payload["value"]
            topic = msg.topic
            logger.debug("Received message on %s: %s", topic, payload)
            with self._state_lock:
                if client is not self.client or self._stopping:
                    return
                if topic.startswith(self.prefix + "/") or is_capability_topic(topic):
                    self._cache[topic] = (payload, received_at)
            self._notify_callbacks(topic, payload)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON on topic %s: %s", msg.topic, msg.payload)
        except Exception:
            logger.exception("Error processing message")

    def _notify_callbacks(self, topic: str, payload: Payload) -> None:
        """Deliver a registration-ordered snapshot without holding a user-code lock."""
        with self._callback_lock:
            if not self._callbacks:
                return
            matches = self._callback_index.iter_match(topic)  # type: ignore[no-untyped-call]
            groups: list[tuple[int, list[Callable[[Payload], None]]]] = sorted(
                matches, key=lambda item: item[0]
            )
            callbacks = tuple(callback for _, group in groups for callback in group)
        # Subscription changes, including those made by callbacks themselves,
        # apply to the next message. The index splits the topic only once and
        # visits matching prefixes instead of scanning all registered filters.
        for callback in callbacks:
            try:
                callback(payload)
            except Exception:
                logger.exception("Callback error")

    def _topic_matches(self, pattern: str, topic: str) -> bool:
        """Match MQTT wildcards, including combined +/# and $-topic rules."""
        return mqtt.topic_matches_sub(pattern, topic)

    def subscribe(self, topic_pattern: str, callback: Callable[[Payload], None]) -> None:
        """Subscribe to a topic pattern with callback."""
        with self._callback_lock:
            if topic_pattern not in self._callbacks:
                self._callbacks[topic_pattern] = []
                self._callback_index[topic_pattern] = (
                    len(self._callbacks),
                    self._callbacks[topic_pattern],
                )
            self._callbacks[topic_pattern].append(callback)
        if self.client and self._connected:
            self.client.subscribe(topic_pattern)

    def unsubscribe(self, topic_pattern: str, callback: Callable[[Payload], None]) -> None:
        """Unsubscribe callback from topic pattern."""
        with self._callback_lock:
            if topic_pattern in self._callbacks:
                self._callbacks[topic_pattern].remove(callback)

    async def connect(self) -> None:
        """Wait for the one owned transport, including its automatic reconnects."""
        # Only creation/retirement is serialized. Concurrent readers wait for the
        # same transport outside this lock, each with its own bounded deadline.
        async with self._lifecycle_lock:
            if self._stopping or (
                self.client is not None
                and (self._loop_thread is None or not self._loop_thread.is_alive())
            ):
                await self._stop_transport()
                if self.client is not None:
                    raise NotConnectedError()
            if self.client is None:
                self._start_transport()
            transport = self.client

        for _ in range(CONNECT_WAIT_STEPS):
            if self.client is not transport or self._stopping:
                raise NotConnectedError()
            if self._connected:
                return
            await asyncio.sleep(CONNECT_POLL_S)
        # A slow reconnect remains owned. A later tool read must not replace it
        # with another connection using the same broker client ID.
        raise ConnectionTimeoutError()

    def _start_transport(self) -> None:
        """Create one transport while holding the lifecycle lock."""
        transport = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=self.config.client_id,
        )
        if self.config.username and self.config.password:
            transport.username_pw_set(self.config.username, self.config.password)
        if self.config.tls:
            transport.tls_set()
        transport.on_connect = self._on_connect
        transport.on_disconnect = self._on_disconnect
        transport.on_message = self._on_message
        transport.connect_async(
            self.config.host, self.config.port, keepalive=MQTT_PROTOCOL_KEEPALIVE_S
        )
        with self._state_lock:
            self.client = transport
            self._stopping = False
            self._connected = False
        self._start_worker()
        self._loop_thread = threading.Thread(
            target=self._run_loop, args=(transport,), name="mqtt-loop", daemon=True
        )
        self._loop_thread.start()

    async def _stop_transport(self) -> None:
        """Bound shutdown without losing ownership of a still-alive worker."""
        with self._state_lock:
            self._stopping = True
            self._connected = False
        if self.client is not None:
            self.client.disconnect()
        self._worker_stop.set()
        # The event also stops a decoder when a full queue cannot take a sentinel.
        with contextlib.suppress(queue.Full):
            self._inbox.put_nowait(None)
        joins = []
        for worker, timeout in (
            (self._worker, WORKER_JOIN_TIMEOUT_S),
            (self._loop_thread, NETWORK_JOIN_TIMEOUT_S),
        ):
            if worker is not None and worker.is_alive():
                joins.append(asyncio.to_thread(worker.join, timeout))
        if joins:
            await asyncio.gather(*joins)
        if self._worker is not None and not self._worker.is_alive():
            self._worker = None
        if self._loop_thread is not None and not self._loop_thread.is_alive():
            self._loop_thread = None
        if self._worker is None and self._loop_thread is None:
            with self._state_lock:
                self.client = None
            # Discard retired telemetry/sentinels; preserve receive timestamps
            # in the existing cache, so its normal freshness checks still apply.
            self._inbox = queue.Queue(maxsize=INBOX_MAXSIZE)
            self._stopping = False
        else:
            logger.warning("MQTT shutdown timed out; workers remain owned")

    async def disconnect(self) -> None:
        """Stop the owned transport; concurrent readers cannot replace it early."""
        async with self._lifecycle_lock:
            await self._stop_transport()
        logger.info("Disconnected from MQTT broker")

    def publish(self, topic: str, payload: Payload, retain: bool = False) -> None:
        """Publish a message to an absolute MQTT topic."""
        if not self.client or not self._connected:
            raise NotConnectedError()

        data = json.dumps(payload) if not isinstance(payload, str) else payload
        self.client.publish(topic, data, retain=retain)

    def read_path(self, device_type: str, instance: int, path: str) -> tuple[Payload, float] | None:
        """Read a cached value from ``N/<portalId>/<type>/<instance>/<path>``.

        Returns ``(value, age_seconds)``, or None when nothing has been received.
        """
        entry = self._cache.get(f"{self.prefix}/{device_type}/{instance}/{path}")
        if entry is None:
            return None
        return entry[0], time.monotonic() - entry[1]

    def read_first(
        self, device_type: str, instance: int, paths: list[str]
    ) -> tuple[Payload, float] | None:
        """Read the first available cached value among candidate item paths."""
        for path in paths:
            result = self.read_path(device_type, instance, path)
            if result is not None:
                return result
        return None

    def read_path_since(
        self, device_type: str, instance: int, path: str, since: float
    ) -> tuple[Payload, float] | None:
        """Only accept cache updates at or after an operation's monotonic start."""
        entry = self._cache.get(f"{self.prefix}/{device_type}/{instance}/{path}")
        if entry is None or entry[1] < since:
            return None
        return entry[0], time.monotonic() - entry[1]

    def list_devices(self) -> list[dict[str, Any]]:
        """List devices discovered from cached ``N/<portalId>/<type>/<instance>`` topics."""
        seen: set[tuple[str, str]] = set()
        devices: list[dict[str, Any]] = []
        # The decoder can add/remove entries while the caller enumerates them.
        for topic in self._cache.copy():
            if not topic.startswith(self.prefix + "/"):
                continue
            rest = topic[len(self.prefix) + 1 :].split("/")
            if len(rest) >= 2 and (rest[0], rest[1]) not in seen:
                seen.add((rest[0], rest[1]))
                try:
                    instance = int(rest[1])
                except ValueError:
                    continue
                devices.append({"device_type": rest[0], "instance": instance})
        return sorted(devices, key=lambda d: (d["device_type"], d["instance"]))

    def discover_instance(self, device_type: str) -> int | None:
        """First discovered instance of ``device_type``, or None when absent."""
        for device in self.list_devices():
            if device["device_type"] == device_type:
                return int(device["instance"])
        return None
