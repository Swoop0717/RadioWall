"""Mirror the live display frame to the LAN as a UDP broadcast.

Every frame rendered to the real panel is also PNG-encoded and sent
to 255.255.255.255:9000 (defaults). Any machine on the LAN running
`python -m radiowall.tools.display_mirror` can see exactly what the
Pi's screen is showing — no IP config on either side.

The PNG compression step matters: raw 240x135 RGB is 97 KB which
doesn't fit in a single UDP datagram (65 KB max). PNG of a typical
amber-on-black frame is 2-8 KB, comfortably in one packet.

Enable by calling install_mirror(device) after make_device(); the
factory wires this automatically when RADIOWALL_MIRROR is set.
"""

from __future__ import annotations

import io
import logging
import os
import socket

log = logging.getLogger(__name__)

DEFAULT_HOST = "255.255.255.255"
DEFAULT_PORT = 9000
MAX_DATAGRAM = 65_000


def _parse_target(value: str) -> tuple[str, int]:
    value = value.strip()
    if value in ("", "1", "true", "on"):
        return DEFAULT_HOST, DEFAULT_PORT
    host, _, port = value.partition(":")
    return (host or DEFAULT_HOST), int(port) if port else DEFAULT_PORT


def install_mirror(device, target: str | None = None) -> None:
    """Monkey-patch `device.display` so each frame is also broadcast.

    If `target` is None, reads RADIOWALL_MIRROR env var. If that's
    unset/empty, does nothing.
    """
    if target is None:
        target = os.getenv("RADIOWALL_MIRROR", "")
    if not target:
        return

    host, port = _parse_target(target)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    original_display = device.display

    def mirrored_display(image):
        original_display(image)
        try:
            buf = io.BytesIO()
            image.save(buf, format="PNG", optimize=False)
            data = buf.getvalue()
            if len(data) > MAX_DATAGRAM:
                log.warning("mirror frame %d B exceeds datagram limit; dropping",
                            len(data))
                return
            sock.sendto(data, (host, port))
        except Exception as e:
            log.warning("mirror send failed: %s", e)

    device.display = mirrored_display
    log.info("display mirror active -> %s:%d", host, port)
