"""MQTT handler for RadioWall.

Subscribes to touch events from the ESP32 and publishes now-playing/status updates.
Uses paho-mqtt for the MQTT client.
"""

import json
import logging
from typing import Callable

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MqttHandler:
    def __init__(self, config: dict):
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 1883)
        self.username = config.get("username")
        self.password = config.get("password")

        topics = config.get("topics", {})
        self.topic_touch = topics.get("touch", "radiowall/touch")
        self.topic_nowplaying = topics.get("nowplaying", "radiowall/nowplaying")
        self.topic_status = topics.get("status", "radiowall/status")
        self.topic_command = topics.get("command", "radiowall/command")

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id="radiowall-server",
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self._on_touch: Callable[[int, int], None] | None = None
        self._on_command: Callable[[str], None] | None = None

    def set_touch_callback(self, callback: Callable[[int, int], None]):
        """Set callback for touch events. Called with (x, y)."""
        self._on_touch = callback

    def set_command_callback(self, callback: Callable[[str], None]):
        """Set callback for command events. Called with command string."""
        self._on_command = callback

    def connect(self):
        """Connect to the MQTT broker."""
        if self.username:
            self._client.username_pw_set(self.username, self.password)

        logger.info("Connecting to MQTT broker at %s:%d", self.host, self.port)
        self._client.connect(self.host, self.port, keepalive=60)

    def start(self):
        """Start the MQTT client loop (blocking)."""
        self.connect()
        self._client.loop_forever()

    def start_background(self):
        """Start the MQTT client loop in a background thread."""
        self.connect()
        self._client.loop_start()

    def stop(self):
        """Stop the MQTT client."""
        self._client.loop_stop()
        self._client.disconnect()

    def publish_now_playing(self, station: str, location: str, country: str):
        """Publish now-playing info to the ESP32."""
        payload = json.dumps({
            "station": station,
            "location": location,
            "country": country,
        })
        self._client.publish(self.topic_nowplaying, payload, qos=1)
        logger.info("Published now-playing: %s (%s, %s)", station, location, country)

    def publish_status(self, state: str, msg: str | None = None):
        """Publish status update. state: 'playing', 'stopped', 'error'."""
        payload = {"state": state}
        if msg:
            payload["msg"] = msg
        self._client.publish(self.topic_status, json.dumps(payload), qos=1)

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(self.topic_touch, qos=1)
            client.subscribe(self.topic_command, qos=1)
            logger.info("Subscribed to %s, %s", self.topic_touch, self.topic_command)
        else:
            logger.error("MQTT connection failed with code %d", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid message on %s: %s", msg.topic, msg.payload)
            return

        if msg.topic == self.topic_touch:
            x = payload.get("x")
            y = payload.get("y")
            if x is not None and y is not None:
                logger.info("Touch event: (%d, %d)", x, y)
                if self._on_touch:
                    self._on_touch(int(x), int(y))
            else:
                logger.warning("Touch event missing x/y: %s", payload)

        elif msg.topic == self.topic_command:
            cmd = payload.get("cmd")
            if cmd:
                logger.info("Command: %s", cmd)
                if self._on_command:
                    self._on_command(cmd)
