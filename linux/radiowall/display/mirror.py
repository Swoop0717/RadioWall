"""Mirror the live display frame to the LAN as a UDP broadcast.

Every frame rendered to the real panel is also PNG-encoded and sent
to 255.255.255.255:9000 (defaults). Any machine on the LAN running
`python -m radiowall.tools.display_mirror` can see exactly what the
Pi's screen is showing — no IP config on either side.

Encoding and sending happen on a background worker thread so the
main render loop never blocks on PNG encode (15-40 ms/frame on a
Pi 3 B+). The queue is tiny (size 1) and newer frames replace older
ones, so "display mirror" always reflects the latest rendered frame
rather than trailing behind.

Enable by calling install_mirror(device) after make_device(); the
factory wires this automatically when RADIOWALL_MIRROR is set.
"""

from __future__ import annotations

import io
import logging
import os
import queue
import socket
import threading

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
    """Monkey-patch `device.display` so each frame is also broadcast
    asynchronously on a worker thread — render loop stays fast."""
    if target is None:
        target = os.getenv("RADIOWALL_MIRROR", "")
    if not target:
        return

    host, port = _parse_target(target)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    original_display = device.display

    # size-1 queue: newest frame wins; a slow network doesn't back up
    # stale frames for the viewer
    pending: queue.Queue = queue.Queue(maxsize=1)

    def worker() -> None:
        while True:
            image = pending.get()
            try:
                buf = io.BytesIO()
                image.save(buf, format="PNG", optimize=False)
                data = buf.getvalue()
                if len(data) > MAX_DATAGRAM:
                    log.warning("mirror frame %d B exceeds datagram limit; dropping",
                                len(data))
                    continue
                sock.sendto(data, (host, port))
            except Exception as e:
                log.warning("mirror send failed: %s", e)

    threading.Thread(target=worker, name="mirror-worker", daemon=True).start()

    def mirrored_display(image):
        original_display(image)
        # copy because luma may reuse its canvas buffer before the worker
        # runs; the copy is cheap (~1 ms) compared to PNG (20+ ms)
        snapshot = image.copy()
        try:
            pending.put_nowait(snapshot)
        except queue.Full:
            # drain the stale frame and put the newest
            try:
                pending.get_nowait()
            except queue.Empty:
                pass
            try:
                pending.put_nowait(snapshot)
            except queue.Full:
                pass

    device.display = mirrored_display
    log.info("display mirror active -> %s:%d (async)", host, port)
