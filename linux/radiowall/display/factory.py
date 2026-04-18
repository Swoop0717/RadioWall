"""Pick a display driver based on env + platform.

Selection order:
  1. RADIOWALL_EMULATE=1        → pygame emulator
  2. RADIOWALL_DISPLAY=<name>   → explicit driver
  3. sys.platform != 'linux'    → emulator
  4. default on linux           → st7789 (current hardware)

Supported drivers: emulator, st7789, ssd1322.

Every returned device exposes `.width` and `.height` — render code
reads those, never hardcoded constants. A display swap is one env var.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

DEFAULT_EMULATOR_W = 240
DEFAULT_EMULATOR_H = 135
DEFAULT_EMULATOR_SCALE = 4

# Adafruit Mini PiTFT 1.14" 240x135 (and Chinese clones): the visible
# panel is a sub-region of the ST7789's 240x320 controller RAM. In
# landscape (MADCTL=0x70), active window starts at (40, 53).
_ST7789_1P14_X_OFFSET = 40
_ST7789_1P14_Y_OFFSET = 53

# Pinout on these boards: DC=GPIO25, backlight=GPIO22, RST not wired.
_ST7789_DC_PIN = 25
_ST7789_BL_PIN = 22


def _pick_driver() -> str:
    if os.getenv("RADIOWALL_EMULATE"):
        return "emulator"
    explicit = os.getenv("RADIOWALL_DISPLAY", "").lower().strip()
    if explicit:
        return explicit
    if sys.platform != "linux":
        return "emulator"
    return "st7789"


def make_device(mock: bool | None = None, scale: int | None = None):
    driver = "emulator" if mock else _pick_driver()
    log.info("display driver: %s", driver)

    if driver == "emulator":
        device = _make_emulator(scale)
    elif driver == "st7789":
        device = _make_st7789()
    elif driver == "ssd1322":
        device = _make_ssd1322()
    else:
        raise ValueError(f"Unknown RADIOWALL_DISPLAY={driver!r}")

    # opt-in LAN mirror: reads RADIOWALL_MIRROR env var
    from radiowall.display.mirror import install_mirror
    install_mirror(device)

    return device


def _make_emulator(scale: int | None):
    from luma.emulator.device import pygame as pygame_device

    w = int(os.getenv("RADIOWALL_EMULATE_W", str(DEFAULT_EMULATOR_W)))
    h = int(os.getenv("RADIOWALL_EMULATE_H", str(DEFAULT_EMULATOR_H)))
    return pygame_device(
        width=w,
        height=h,
        mode="RGB",
        transform="identity",
        scale=scale or DEFAULT_EMULATOR_SCALE,
        frame_rate=60,
    )


def _make_st7789():
    from luma.core.interface.serial import spi
    from luma.lcd.device import st7789

    # luma.lcd's st7789 writes pixels at controller-memory (0,0) with
    # no offset logic — correct for 240x240 and 240x320 panels, wrong
    # for 240x135 sub-panels. Subclass and shift the CASET/RASET
    # window by the panel's offset in controller RAM.
    class st7789_135(st7789):
        def set_window(self, x1, y1, x2, y2):
            x1 += _ST7789_1P14_X_OFFSET
            x2 += _ST7789_1P14_X_OFFSET
            y1 += _ST7789_1P14_Y_OFFSET
            y2 += _ST7789_1P14_Y_OFFSET
            self.command(0x2A, x1 >> 8, x1 & 0xFF, (x2 - 1) >> 8, (x2 - 1) & 0xFF)
            self.command(0x2B, y1 >> 8, y1 & 0xFF, (y2 - 1) >> 8, (y2 - 1) & 0xFF)
            self.command(0x2C)

    # Orientation is board-mount-dependent — HAT could be attached
    # either way up in the frame. Controller is hardware-landscape
    # via MADCTL=0x70; rotate=0 or 2 keeps the 240x135 aspect ratio
    # (rotate=1/3 would swap width/height via capabilities() which
    # breaks offsets and layout assumptions). Override with
    # RADIOWALL_DISPLAY_ROTATE=0|2 — default 0.
    rotate = int(os.getenv("RADIOWALL_DISPLAY_ROTATE", "0"))
    if rotate not in (0, 2):
        log.warning("RADIOWALL_DISPLAY_ROTATE=%d unsupported on ST7789 1.14\"; "
                    "forcing 0. 1/3 swap dims and need different offsets.", rotate)
        rotate = 0

    return st7789_135(
        spi(port=0, device=0, gpio_DC=_ST7789_DC_PIN, gpio_RST=None,
            bus_speed_hz=40_000_000),
        width=240,
        height=135,
        rotate=rotate,
        gpio_LIGHT=_ST7789_BL_PIN,
        active_low=False,
    )


def _make_ssd1322():
    from luma.core.interface.serial import spi
    from luma.oled.device import ssd1322

    return ssd1322(spi(port=0, device=0), width=256, height=64)
