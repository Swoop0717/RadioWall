"""Pick the real OLED driver or the pygame emulator based on env/config.

Both return a luma.core device that speaks the same API, so the rest of
the code never cares which one it got.
"""

from __future__ import annotations

import os

WIDTH = 256
HEIGHT = 64
DEFAULT_EMULATOR_SCALE = 10  # 256x64 → 2560x640


def make_device(mock: bool | None = None, scale: int | None = None):
    """Return a luma device. Emulator if `mock` is True or $RADIOWALL_EMULATE is set."""
    if mock is None:
        mock = bool(os.getenv("RADIOWALL_EMULATE"))

    if mock:
        from luma.emulator.device import pygame as pygame_device
        return pygame_device(
            width=WIDTH,
            height=HEIGHT,
            mode="RGB",                      # RGB lets us tint the output amber
            transform="identity",            # nearest-neighbor integer scale; crisp pixels
            scale=scale or DEFAULT_EMULATOR_SCALE,
            frame_rate=60,
        )

    from luma.core.interface.serial import spi
    from luma.oled.device import ssd1322

    # spidev0.0 on Pi 3 B+; overridable from config.yaml later
    return ssd1322(spi(port=0, device=0), width=WIDTH, height=HEIGHT)
