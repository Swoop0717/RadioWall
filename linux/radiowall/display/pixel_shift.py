"""OLED burn-in protection: drift the whole frame 1 px around a tiny
orbit, changing position every few minutes — the same trick TVs use.

The display is always on showing a mostly-static layout (user's
explicit choice), which is exactly the burn-in worst case for an OLED.
A 1 px shift is invisible at arm's length but spreads the wear of
every static edge across neighboring pixels.

Installed by the display factory as a wrapper around device.display()
(same pattern as the LAN mirror), so all screens are covered without
any draw-code cooperation. The redraw-skipping main loop repaints at
least ~once a second (blink/heartbeat), so a new offset takes effect
promptly. Default on for the SSD1322 OLED, off elsewhere;
RADIOWALL_PIXEL_SHIFT=0/1 overrides either way.
"""

from __future__ import annotations

import logging
import os
import time

from PIL import Image

log = logging.getLogger(__name__)

PERIOD_S = 240.0                      # one orbit step every 4 minutes
_ORBIT = [(0, 0), (1, 0), (1, 1), (0, 1)]


def offset_at(t: float) -> tuple[int, int]:
    """Orbit position for a monotonic timestamp. Pure — unit-testable."""
    return _ORBIT[int(t / PERIOD_S) % len(_ORBIT)]


def install_pixel_shift(device, default_on: bool) -> None:
    env = os.getenv("RADIOWALL_PIXEL_SHIFT", "").strip()
    enabled = default_on if env == "" else env not in ("0", "false", "off")
    if not enabled:
        return

    orig_display = device.display

    def shifted_display(image):
        dx, dy = offset_at(time.monotonic())
        if (dx, dy) != (0, 0):
            canvas = Image.new(image.mode, image.size)
            canvas.paste(image, (dx, dy))
            image = canvas
        orig_display(image)

    device.display = shifted_display
    log.info("pixel shift enabled (1px orbit, %.0fs steps)", PERIOD_S)
