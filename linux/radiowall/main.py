"""Entry point — minimum viable bring-up.

Mockup of the eventual "now playing" screen, styled after an old VFD
car-radio display. No real data yet — lets you eyeball the layout.
"""

from __future__ import annotations

import argparse
import time

from luma.core.render import canvas

from radiowall.display import fonts
from radiowall.display.factory import HEIGHT, WIDTH, make_device

AMBER = (255, 176, 0)       # classic VFD color
AMBER_DIM = (110, 75, 0)    # for the separator and bg accents


def draw_mockup(device, frame: int) -> None:
    # simple horizontal scroll of the bottom "now playing" text
    marquee = " · Blue in Green — Miles Davis    "
    scroll_len = 36
    offset = frame % len(marquee)
    visible = (marquee + marquee)[offset:offset + scroll_len]

    with canvas(device) as draw:
        # --- top-right indicators: FM · ST · P2 ---
        right_edge = WIDTH - 4
        indicators = "FM · ST · P2"
        w = draw.textlength(indicators, font=fonts.TINY)
        draw.text((right_edge - w, 2), indicators, font=fonts.TINY, fill=AMBER)

        # --- tiny signal bars top-left ---
        base_y = 10
        for i, h in enumerate([2, 4, 6, 8]):
            x = 4 + i * 3
            draw.rectangle((x, base_y - h, x + 2, base_y), fill=AMBER)

        # --- station name: big, left-aligned, top half ---
        draw.text((4, 14), "Radio Orange", font=fonts.BIG, fill=AMBER)

        # --- metadata line: city · country · freq ---
        draw.text((4, 42), "Vienna  AT  ·  94.0", font=fonts.MED, fill=AMBER)

        # --- thin separator just above the bottom line ---
        draw.line((0, HEIGHT - 12, WIDTH, HEIGHT - 12), fill=AMBER_DIM)

        # --- scrolling "now playing" bottom strip ---
        draw.text((4, HEIGHT - 10), visible, font=fonts.TINY, fill=AMBER)


def main() -> int:
    parser = argparse.ArgumentParser(description="RadioWall — Linux port")
    parser.add_argument(
        "--emulate",
        action="store_true",
        help="Force pygame emulator (also works via RADIOWALL_EMULATE=1)",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=None,
        help="Emulator window scale (default: 10 → 2560x640)",
    )
    args = parser.parse_args()

    device = make_device(mock=args.emulate or None, scale=args.scale)

    try:
        frame = 0
        while True:
            draw_mockup(device, frame)
            frame += 1
            time.sleep(0.15)   # marquee speed
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
