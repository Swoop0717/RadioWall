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


def fonts_for(height: int) -> FontSet:
    """Font set sized as fractions of display height.

    Fractions tuned for ~240x135 TFTs viewed at arm's length — legible
    across a room, not screen-real-estate efficient. Re-tune if the
    layout ever needs to cram more lines on the panel.
    """
    return FontSet(
        big=load(max(12, int(height * 0.52))),
        med=load(max(10, int(height * 0.26))),
        small=load(max(8, int(height * 0.20))),
        tiny=load(max(7, int(height * 0.16))),
    )


# Backward-compat constants sized for a 64 px display (original SSD1322 target).
# New code should use fonts_for(device.height) instead.
BIG = load(28)
MED = load(14)
SMALL = load(10)
TINY = load(8)
