"""RadioWall server - main orchestration.

Receives touch events via MQTT, finds nearby radio stations,
and streams them to a UPnP speaker.
"""

import asyncio
import logging
import sys
from pathlib import Path

import yaml

from coordinates import CoordinateConverter
from mqtt_handler import MqttHandler
from radio_garden import RadioGardenClient
from upnp_streamer import UpnpStreamer

logger = logging.getLogger("radiowall")


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        logger.error("config.yaml not found. Copy config.example.yaml to config.yaml")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file")

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


class RadioWallServer:
    def __init__(self, config: dict):
        self.config = config
        self.converter = CoordinateConverter(config.get("calibration", {}))
        self.radio = RadioGardenClient(config.get("radio_garden", {}))
        self.upnp = UpnpStreamer(config.get("upnp", {}))
        self.mqtt = MqttHandler(config.get("mqtt", {}))
        self._loop = asyncio.new_event_loop()

    def start(self):
        logger.info("Starting RadioWall server")

        # Pre-discover UPnP speaker (non-fatal if not found)
        try:
            self._loop.run_until_complete(self.upnp.discover())
        except Exception:
            logger.warning("UPnP discovery failed at startup, will retry on first touch")

        # Wire up MQTT callbacks
        self.mqtt.set_touch_callback(self._handle_touch)
        self.mqtt.set_command_callback(self._handle_command)

        # Start MQTT (blocks)
        logger.info("Listening for touch events...")
        self.mqtt.start()

    def _handle_touch(self, x: int, y: int):
        """Called when a touch event is received from the ESP32."""
        lat, lon = self.converter.pixel_to_latlon(x, y)
        logger.info("Touch (%d, %d) -> coordinates (%.2f, %.2f)", x, y, lat, lon)

        self.mqtt.publish_status("loading")

        try:
            result = self.radio.find_nearest_stations(lat, lon)
        except Exception:
            logger.exception("Failed to find stations")
            self.mqtt.publish_status("error", "No stations found")
            return

        station_name = result["station_name"]
        location = result["location"]
        country = result["country"]
        stream_url = result["stream_url"]

        logger.info("Playing %s from %s, %s", station_name, location, country)

        # Stream to speaker
        success = self._loop.run_until_complete(
            self.upnp.play(stream_url, title=f"{station_name} - {location}")
        )

        if success:
            self.mqtt.publish_now_playing(station_name, location, country)
            self.mqtt.publish_status("playing")
        else:
            self.mqtt.publish_status("error", "Playback failed")

    def _handle_command(self, cmd: str):
        """Called when a command is received from the ESP32."""
        if cmd == "stop":
            self._loop.run_until_complete(self.upnp.stop())
            self.mqtt.publish_status("stopped")
        elif cmd == "replay":
            logger.info("Replay not yet implemented")
        else:
            logger.warning("Unknown command: %s", cmd)


def main():
    config = load_config()
    setup_logging(config)

    server = RadioWallServer(config)
    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.mqtt.stop()


if __name__ == "__main__":
    main()
