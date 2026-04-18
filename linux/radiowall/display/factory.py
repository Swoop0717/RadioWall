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

# ST7789 Pi TFT 1.14" (Adafruit Mini PiTFT + clones): backlight on GPIO 22.
# We hold the line HIGH for the process lifetime via gpiod v2.
_ST7789_BACKLIGHT_PIN = 22
_backlight_handle = None


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
        return _make_emulator(scale)
    if driver == "st7789":
        return _make_st7789()
    if driver == "ssd1322":
        return _make_ssd1322()
    raise ValueError(f"Unknown RADIOWALL_DISPLAY={driver!r}")


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
    _set_backlight_on()
    from luma.core.interface.serial import spi
    from luma.lcd.device import st7789

    # Adafruit Mini PiTFT 1.14" (and clones):
    #   DC = GPIO 25, RST = not wired (self-reset via POR), CS = CE0
    # luma.lcd computes the offsets into the controller's 240x320 frame
    # internally from (width, height, rotate).
    return st7789(
        spi(port=0, device=0, gpio_DC=25, gpio_RST=None, bus_speed_hz=40_000_000),
        width=240,
        height=135,
        rotate=1,
        bgr=False,
    )


def _make_ssd1322():
    from luma.core.interface.serial import spi
    from luma.oled.device import ssd1322

    return ssd1322(spi(port=0, device=0), width=256, height=64)


def _set_backlight_on() -> None:
    """Drive the ST7789 backlight pin HIGH via gpiod v2. Idempotent."""
    global _backlight_handle
    if _backlight_handle is not None:
        return
    try:
        import gpiod
        from gpiod.line import Direction, Value

        _backlight_handle = gpiod.request_lines(
            "/dev/gpiochip0",
            consumer="radiowall-bl",
            config={
                _ST7789_BACKLIGHT_PIN: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.ACTIVE,
                )
            },
        )
    except Exception as e:
        log.warning("backlight GPIO %d not driven (%s) — screen may stay dark",
                    _ST7789_BACKLIGHT_PIN, e)
