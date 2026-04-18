"""Font loading with platform-aware fallbacks.

Emulator dev on Windows → Arial bold.
Real Pi → DejaVu Sans (ships with DietPi).
Fallback → PIL default.

`fonts_for(height)` returns a FontSet sized relative to the display
height. That's the display-agnostic entry point — render code should
ask for a set based on `device.height` rather than importing module
globals, so the same code looks OK on a 64 px OLED and a 135 px TFT.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from PIL import ImageFont

if sys.platform == "win32":
    _CANDIDATES = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
else:
    _CANDIDATES = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def load(size: int) -> ImageFont.ImageFont:
    for path in _CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


@dataclass(frozen=True)
class FontSet:
    big: ImageFont.ImageFont
    med: ImageFont.ImageFont
    small: ImageFont.ImageFont
    tiny: ImageFont.ImageFont


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def fonts_for(height: int) -> FontSet:
    """Font set sized as fractions of display height.

    Every level is env-overridable for live tuning without commits:
      RADIOWALL_FONT_BIG    (default 0.42)
      RADIOWALL_FONT_MED    (default 0.26)
      RADIOWALL_FONT_SMALL  (default 0.20)
      RADIOWALL_FONT_TINY   (default 0.16)
    """
    big = _env_float("RADIOWALL_FONT_BIG", 0.42)
    med = _env_float("RADIOWALL_FONT_MED", 0.26)
    small = _env_float("RADIOWALL_FONT_SMALL", 0.20)
    tiny = _env_float("RADIOWALL_FONT_TINY", 0.16)
    return FontSet(
        big=load(max(12, int(height * big))),
        med=load(max(10, int(height * med))),
        small=load(max(8, int(height * small))),
        tiny=load(max(7, int(height * tiny))),
    )


# Backward-compat constants sized for a 64 px display (original SSD1322 target).
# New code should use fonts_for(device.height) instead.
BIG = load(28)
MED = load(14)
SMALL = load(10)
TINY = load(8)
