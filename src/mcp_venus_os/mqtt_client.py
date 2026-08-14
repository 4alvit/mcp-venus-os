"""MQTT client for real-time Venus OS data streaming."""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from .config import get_config
from .dbus_client import BatteryData, GridData, InverterData, PVData

logger = logging.getLogger(__name__)


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
        self._callbacks: dict[str, list[Callable[[Payload], None]]] = {}

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,  # noqa: ANN401
        flags: Any,  # noqa: ANN401
        reason_code: mqtt.ReasonCode,  # type: ignore[name-defined]
        properties: mqtt.Properties,  # type: ignore[name-defined]
    ) -> None:
        """MQTT on_connect callback."""
        if reason_code == 0:
            self._connected = True
            logger.info("Connected to MQTT broker at %s:%d", self.config.host, self.config.port)
            base = self.config.base_topic
            client.subscribe(f"{base}/+/+/+")
            client.subscribe(f"{base}/+/+/+/+")
            logger.debug("Subscribed to %s", base)
        else:
            logger.error("Failed to connect to MQTT broker: %d", reason_code)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,  # noqa: ANN401
        flags: Any,  # noqa: ANN401
        reason_code: mqtt.ReasonCode,  # type: ignore[name-defined]
        properties: mqtt.Properties,  # type: ignore[name-defined]
    ) -> None:
        """MQTT on_disconnect callback."""
        self._connected = False
        logger.warning("Disconnected from MQTT broker: %d", reason_code)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,  # noqa: ANN401
        msg: mqtt.MQTTMessage,
    ) -> None:
        """MQTT on_message callback."""
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            logger.debug("Received message on %s: %s", topic, payload)
            self._notify_callbacks(topic, payload)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON on topic %s: %s", msg.topic, msg.payload)
        except Exception:
            logger.exception("Error processing message")

    def _notify_callbacks(self, topic: str, payload: Payload) -> None:
        """Notify registered callbacks for a topic."""
        for pattern, callbacks in self._callbacks.items():
            if self._topic_matches(pattern, topic):
                for callback in callbacks:
                    try:
                        callback(payload)
                    except Exception:
                        logger.exception("Callback error")

    def _topic_matches(self, pattern: str, topic: str) -> bool:
        """Check if topic matches pattern (supports wildcards)."""
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")
        if len(pattern_parts) != len(topic_parts):
            return False
        for p, t in zip(pattern_parts, topic_parts, strict=False):
            if p != "+" and p != "#" and p != t:
                return False
        return True

    def subscribe(self, topic_pattern: str, callback: Callable[[Payload], None]) -> None:
        """Subscribe to a topic pattern with callback."""
        if topic_pattern not in self._callbacks:
            self._callbacks[topic_pattern] = []
        self._callbacks[topic_pattern].append(callback)
        if self.client and self._connected:
            self.client.subscribe(topic_pattern)

    def unsubscribe(self, topic_pattern: str, callback: Callable[[Payload], None]) -> None:
        """Unsubscribe callback from topic pattern."""
        if topic_pattern in self._callbacks:
            self._callbacks[topic_pattern].remove(callback)

    async def connect(self) -> None:
        """Connect to MQTT broker."""
        if self._connected:
            return

        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=self.config.client_id,
        )

        if self.config.username and self.config.password:
            self.client.username_pw_set(self.config.username, self.config.password)

        if self.config.tls:
            self.client.tls_set()

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self.client.connect_async(self.config.host, self.config.port)
        self.client.loop_start()

        # Wait for connection
        for _ in range(50):
            if self._connected:
                break
            await asyncio.sleep(0.1)
        else:
            raise ConnectionTimeoutError()

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self.client and self._connected:
            self.client.loop_stop()
            self.client.disconnect()
            self._connected = False
            logger.info("Disconnected from MQTT broker")

    def publish(self, topic: str, payload: Payload, retain: bool = False) -> None:
        """Publish a message to MQTT."""
        if not self.client or not self._connected:
            raise NotConnectedError()

        data = json.dumps(payload) if not isinstance(payload, str) else payload
        self.client.publish(f"{self.config.base_topic}/{topic}", data, retain=retain)

    def publish_battery(self, instance: int, data: BatteryData) -> None:
        """Publish battery data."""
        self.publish(f"battery/{instance}", asdict(data))

    def publish_pv(self, instance: int, data: PVData) -> None:
        """Publish PV data."""
        self.publish(f"solarcharger/{instance}", asdict(data))

    def publish_grid(self, instance: int, data: GridData) -> None:
        """Publish grid data."""
        self.publish(f"vebus/{instance}/grid", asdict(data))

    def publish_inverter(self, instance: int, data: InverterData) -> None:
        """Publish inverter data."""
        self.publish(f"vebus/{instance}/inverter", asdict(data))
