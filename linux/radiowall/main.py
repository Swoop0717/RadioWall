"""Entry point — VFD-style "now playing" mockup.

Layout is defined in fractions of the device's width/height so the
same code renders sensibly on anything from a 256x64 mono OLED to a
240x135 color TFT. Pixel-perfect tuning per display is future work.
"""

from __future__ import annotations

import argparse
import logging
import time

from luma.core.render import canvas

from radiowall.display import fonts
from radiowall.display.factory import make_device
from radiowall.logging_setup import setup as setup_logging

log = logging.getLogger(__name__)

AMBER = (255, 176, 0)       # classic VFD color
AMBER_DIM = (110, 75, 0)    # separator / bg accents


SCROLL_PX_PER_FRAME = 1    # pixels per tick; smaller = slower, smoother


def draw_mockup(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    pad = max(2, W // 64)

    # mock data that eventually comes from AppState
    top_line = "Vienna  AT  ·  3/12"
    bottom_line = "vol 45  ·  94.0  ·  WiiM"
    scroll = "Radio Wien  ·  Blue in Green  ·  Miles Davis  ·  "

    with canvas(device) as draw:
        # --- top info band ---
        draw.text((pad, pad), top_line, font=fs.small, fill=AMBER)

        # --- separators framing the middle scroll band ---
        top_sep_y = int(H * 0.18)
        bot_sep_y = int(H * 0.82)
        draw.line((0, top_sep_y, W, top_sep_y), fill=AMBER_DIM)
        draw.line((0, bot_sep_y, W, bot_sep_y), fill=AMBER_DIM)

        # --- middle: pixel-smooth horizontal scroll ---
        band_top = top_sep_y + 2
        band_h = bot_sep_y - top_sep_y
        y_text = band_top + max(0, (band_h - fs.big.size) // 2)
        text_w = max(1, int(draw.textlength(scroll, font=fs.big)))
        offset_px = (frame * SCROLL_PX_PER_FRAME) % text_w
        # draw text twice back-to-back so it wraps cleanly regardless
        # of whether text_w is larger or smaller than the display width
        draw.text((-offset_px, y_text), scroll, font=fs.big, fill=AMBER)
        draw.text((-offset_px + text_w, y_text), scroll, font=fs.big, fill=AMBER)

        # --- bottom info band ---
        draw.text((pad, bot_sep_y + pad), bottom_line, font=fs.small, fill=AMBER)


def main() -> int:
    parser = argparse.ArgumentParser(description="RadioWall — Linux port")
    parser.add_argument(
        "--emulate",
        action="store_true",
        help="Force pygame emulator (also: RADIOWALL_EMULATE=1)",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=None,
        help="Emulator window scale (default: 4)",
    )
    args = parser.parse_args()

    setup_logging()
    log.info("radiowall starting")

    device = make_device(mock=args.emulate or None, scale=args.scale)
    log.info("display ready: %dx%d", device.width, device.height)
    fs = fonts.fonts_for(device.height)

    try:
        frame = 0
        while True:
            draw_mockup(device, frame, fs)
            frame += 1
            time.sleep(0.04)   # ~25 fps
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
