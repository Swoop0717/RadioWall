"""Board profiles: which SPI bus and GPIO lines the peripherals sit on.

The wiring is identical across boards — same physical header positions
(the 40-pin layouts match) — but the *numbers* behind those positions
differ per SoC, as does the GPIO access library:

                          Raspberry Pi 3B+   Orange Pi Zero 3W (A733)
    SPI bus / dev         /dev/spidev0.0     /dev/spidev3.0
    display DC   (phys 22)  BCM 25           gpiochip0 line 96  (PD0)
    display BL   (phys 15)  BCM 22           gpiochip0 line 137 (PE9)
    encoder CLK  (phys 40)  BCM 21           gpiochip0 line 39  (PB7)
    encoder DT   (phys 38)  BCM 20           gpiochip0 line 40  (PB8)
    encoder SW   (phys 36)  BCM 16           gpiochip0 line 98  (PD2)
    GPIO library            RPi.GPIO         gpiod v2 (via GpiodGPIO shim)

Detection order:
  1. RADIOWALL_BOARD env var ("pi" | "opizero3w")
  2. /proc/device-tree/model contains "Raspberry Pi" → pi
  3. /proc/device-tree/model starts with "sun60iw2" (the A733's generic
     SoC string — the vendor DT carries no board name) → opizero3w
  4. fallback → pi (preserves the original behavior)

Orange Pi prerequisite: SPI3 overlay enabled in /boot/orangepiEnv.txt
(`overlays=spi3-cs0-cs1-spidev`), else /dev/spidev3.0 doesn't exist.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BoardProfile:
    name: str
    spi_port: int
    spi_device: int
    dc_pin: int          # physical pin 22 (shared by ST7789 HAT + SSD1322)
    backlight_pin: int   # physical pin 15 — ST7789 HAT backlight
    rst_pin: int         # physical pin 15 — SSD1322 reset (pin freed once
                         # the HAT is gone; the two displays never coexist)
    encoder_clk: int
    encoder_dt: int
    encoder_sw: int
    # None → use RPi.GPIO; a chip path → use the gpiod-backed shim with
    # pin numbers meaning line offsets on that chip.
    gpio_chip: str | None


PI = BoardProfile(
    name="pi",
    spi_port=0, spi_device=0,
    dc_pin=25, backlight_pin=22, rst_pin=22,
    encoder_clk=21, encoder_dt=20, encoder_sw=16,
    gpio_chip=None,
)

OPI_ZERO3W = BoardProfile(
    name="opizero3w",
    spi_port=3, spi_device=0,
    dc_pin=96, backlight_pin=137, rst_pin=137,
    encoder_clk=39, encoder_dt=40, encoder_sw=98,
    gpio_chip="/dev/gpiochip0",
)

_PROFILES = {p.name: p for p in (PI, OPI_ZERO3W)}


def _read_dt_model() -> str:
    try:
        with open("/proc/device-tree/model", "rb") as f:
            return f.read().rstrip(b"\x00").decode(errors="replace")
    except OSError:
        return ""


@lru_cache(maxsize=1)
def get_profile() -> BoardProfile:
    explicit = os.getenv("RADIOWALL_BOARD", "").strip().lower()
    if explicit:
        try:
            profile = _PROFILES[explicit]
        except KeyError:
            raise ValueError(
                f"Unknown RADIOWALL_BOARD={explicit!r}; "
                f"choose one of {sorted(_PROFILES)}"
            ) from None
        log.info("board profile (from env): %s", profile.name)
        return profile

    model = _read_dt_model()
    if "Raspberry Pi" in model:
        profile = PI
    elif model.startswith("sun60iw2"):
        profile = OPI_ZERO3W
    else:
        profile = PI
    log.info("board profile (model=%r): %s", model, profile.name)
    return profile


@lru_cache(maxsize=1)
def get_gpio():
    """The RPi.GPIO-compatible GPIO object for this board, or None.

    None means no GPIO available (dev laptop) — callers treat the
    peripheral as absent, same as the old RPi.GPIO ImportError path.
    """
    profile = get_profile()
    if profile.gpio_chip is None:
        try:
            import RPi.GPIO as GPIO
            return GPIO
        except ImportError:
            return None
    try:
        from radiowall.hw.gpio_compat import GpiodGPIO
        return GpiodGPIO(profile.gpio_chip)
    except (ImportError, OSError) as e:
        log.warning("gpiod backend unavailable (%s); GPIO disabled", e)
        return None
