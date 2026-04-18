"""Font loading with platform-aware fallbacks.

Emulator dev on Windows → Arial bold (looks fine).
Real Pi → DejaVu Sans (ships with DietPi).
Fallback → PIL default (ugly but functional).
"""

from __future__ import annotations

import sys

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


# pre-loaded common sizes
BIG = load(28)
MED = load(14)
SMALL = load(10)
TINY = load(8)
