"""Entry point — VFD-style "now playing" mockup.

Layout is defined in fractions of the device's width/height so the
same code renders sensibly on anything from a 256x64 mono OLED to a
240x135 color TFT. Pixel-perfect tuning per display is future work.
"""

from __future__ import annotations

import argparse
import time

from luma.core.render import canvas

from radiowall.display import fonts
from radiowall.display.factory import make_device

AMBER = (255, 176, 0)       # classic VFD color
AMBER_DIM = (110, 75, 0)    # separator / bg accents


def draw_mockup(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    pad = max(2, W // 64)

    # bottom marquee scroll
    marquee = " · Blue in Green — Miles Davis    "
    scroll_len = max(16, W // 7)
    offset = frame % len(marquee)
    visible = (marquee + marquee)[offset:offset + scroll_len]

    with canvas(device) as draw:
        # --- top band: signal bars (left), indicators (right) ---
        top_baseline = int(H * 0.18)
        bar_bottom = top_baseline
        for i, frac in enumerate([0.25, 0.5, 0.75, 1.0]):
            x = pad + i * (pad + 1)
            bar_h = max(1, int(top_baseline * frac * 0.8))
            draw.rectangle(
                (x, bar_bottom - bar_h, x + max(1, pad // 2), bar_bottom),
                fill=AMBER,
            )

        indicators = "FM · ST · P2"
        iw = draw.textlength(indicators, font=fs.tiny)
        draw.text((W - pad - iw, pad), indicators, font=fs.tiny, fill=AMBER)

        # --- station name: big, left-aligned, starts just below top band ---
        draw.text((pad, int(H * 0.22)), "Radio Orange", font=fs.big, fill=AMBER)

        # --- metadata line ---
        draw.text(
            (pad, int(H * 0.65)),
            "Vienna  AT  ·  94.0",
            font=fs.med,
            fill=AMBER,
        )

        # --- separator above marquee ---
        sep_y = int(H * 0.88)
        draw.line((0, sep_y, W, sep_y), fill=AMBER_DIM)

        # --- scrolling marquee ---
        draw.text(
            (pad, sep_y + max(1, (H - sep_y) // 6)),
            visible,
            font=fs.tiny,
            fill=AMBER,
        )


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

    device = make_device(mock=args.emulate or None, scale=args.scale)
    fs = fonts.fonts_for(device.height)

    try:
        frame = 0
        while True:
            draw_mockup(device, frame, fs)
            frame += 1
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
