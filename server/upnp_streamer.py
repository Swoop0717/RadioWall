"""UPnP/DLNA streamer for sending audio to network speakers (e.g. WiiM Amp Pro)."""

import asyncio
import logging

from async_upnp_client.aiohttp import AiohttpRequester
from async_upnp_client.client import UpnpDevice
from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.search import async_search
from async_upnp_client.utils import CaseInsensitiveDict

logger = logging.getLogger(__name__)

DIDL_TEMPLATE = """<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
  <item id="0" parentID="0" restricted="1">
    <dc:title>{title}</dc:title>
    <upnp:class>object.item.audioItem.audioBroadcast</upnp:class>
    <res protocolInfo="http-get:*:audio/mpeg:*">{url}</res>
  </item>
</DIDL-Lite>"""


class UpnpStreamer:
    def __init__(self, config: dict):
        self.device_name = config.get("device_name")
        self.discovery_timeout = config.get("discovery_timeout", 5)
        self.default_volume = config.get("default_volume")
        self._device: UpnpDevice | None = None
        self._requester = AiohttpRequester()

    async def discover(self) -> str | None:
        """Discover UPnP media renderers on the network.

        Returns the friendly name of the selected device, or None if not found.
        """
        logger.info("Scanning for UPnP devices (timeout=%ds)...", self.discovery_timeout)

        # Collect SSDP responses via callback
        locations: list[str] = []

        async def _on_response(headers: CaseInsensitiveDict) -> None:
            location = headers.get("location")
            if location and location not in locations:
                locations.append(location)

        await async_search(_on_response, timeout=self.discovery_timeout)

        for location in locations:
            try:
                factory = UpnpFactory(self._requester)
                device = await factory.async_create_device(location)

                # Check if it's a media renderer
                av_transport = device.service(
                    "urn:schemas-upnp-org:service:AVTransport:1"
                )
                if av_transport is None:
                    continue

                name = device.friendly_name
                logger.info("Found renderer: %s", name)

                if self.device_name is None or self.device_name.lower() in name.lower():
                    self._device = device
                    logger.info("Selected renderer: %s", name)
                    return name

            except Exception:
                logger.debug("Failed to query device at %s", location)
                continue

        logger.warning("No suitable UPnP renderer found")
        return None

    async def play(self, stream_url: str, title: str = "RadioWall") -> bool:
        """Send a stream URL to the UPnP renderer for playback.

        Returns True on success.
        """
        if self._device is None:
            if await self.discover() is None:
                logger.error("No UPnP device available")
                return False

        av_transport = self._device.service(
            "urn:schemas-upnp-org:service:AVTransport:1"
        )
        if av_transport is None:
            logger.error("Device has no AVTransport service")
            return False

        try:
            # Stop current playback
            stop_action = av_transport.action("Stop")
            await stop_action.async_call(InstanceID=0)
        except Exception:
            pass  # May fail if nothing is playing

        # Set volume if configured
        if self.default_volume is not None:
            try:
                rc = self._device.service(
                    "urn:schemas-upnp-org:service:RenderingControl:1"
                )
                if rc:
                    set_vol = rc.action("SetVolume")
                    await set_vol.async_call(
                        InstanceID=0,
                        Channel="Master",
                        DesiredVolume=self.default_volume,
                    )
            except Exception:
                logger.warning("Failed to set volume")

        # Build DIDL-Lite metadata
        safe_title = title.replace("&", "&amp;").replace("<", "&lt;")
        safe_url = stream_url.replace("&", "&amp;")
        metadata = DIDL_TEMPLATE.format(title=safe_title, url=safe_url)

        try:
            set_uri = av_transport.action("SetAVTransportURI")
            await set_uri.async_call(
                InstanceID=0,
                CurrentURI=stream_url,
                CurrentURIMetaData=metadata,
            )

            play_action = av_transport.action("Play")
            await play_action.async_call(InstanceID=0, Speed="1")

            logger.info("Playing: %s -> %s", title, stream_url)
            return True

        except Exception:
            logger.exception("Failed to start playback")
            return False

    async def stop(self) -> bool:
        """Stop current playback."""
        if self._device is None:
            return True

        av_transport = self._device.service(
            "urn:schemas-upnp-org:service:AVTransport:1"
        )
        if av_transport is None:
            return False

        try:
            stop_action = av_transport.action("Stop")
            await stop_action.async_call(InstanceID=0)
            logger.info("Playback stopped")
            return True
        except Exception:
            logger.exception("Failed to stop playback")
            return False
