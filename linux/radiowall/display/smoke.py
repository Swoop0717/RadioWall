"""Display smoke test — fill screen red, green, blue, white, black.

Run with:
    python -m radiowall.display.smoke

Fastest way to verify a new driver / wiring / offsets before writing
layout code. If colors are swapped, flip `bgr` in the driver. If the
image is shifted, tune the h_offset / v_offset.
"""

from __future__ import annotations

import time

from luma.core.render import canvas

from radiowall.display.factory import make_device
from radiowall.logging_setup import setup as setup_logging


COLORS = [
    ("red", (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("white", (255, 255, 255)),
    ("black", (0, 0, 0)),
]


def main() -> int:
    setup_logging()
    device = make_device()
    W, H = device.width, device.height
    print(f"device: {W}x{H}")

    for name, rgb in COLORS:
        print(f"  -> {name} {rgb}")
        with canvas(device) as draw:
            draw.rectangle((0, 0, W - 1, H - 1), fill=rgb)
        time.sleep(1.2)

    # final: corner markers so you can tell orientation + offset issues
    with canvas(device) as draw:
        draw.rectangle((0, 0, W - 1, H - 1), outline=(255, 255, 255))
        draw.rectangle((0, 0, 4, 4), fill=(255, 0, 0))         # TL red
        draw.rectangle((W - 5, 0, W - 1, 4), fill=(0, 255, 0))  # TR green
        draw.rectangle((0, H - 5, 4, H - 1), fill=(0, 0, 255))  # BL blue
        draw.rectangle((W - 5, H - 5, W - 1, H - 1),
                       fill=(255, 255, 0))                      # BR yellow
    print("done; corners: TL=red TR=green BL=blue BR=yellow")
    time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
