"""Entry point — VFD-style mockup + visualizer demo, button-togglable.

Layout is defined in fractions of the device's width/height so the
same code renders sensibly on anything from a 256x64 mono OLED to a
240x135 color TFT. Pixel-perfect tuning per display is future work.

Button A (GPIO 23) = cycle screen mode; Button B (GPIO 24) = reset
to mockup. Buttons are active-low with internal pull-up. On non-Pi
environments (Windows emulator, missing RPi.GPIO) the button path
is a no-op.
"""

from __future__ import annotations

import argparse
import logging
import time

from luma.core.render import canvas

from radiowall.display import fonts, visualizer
from radiowall.display.factory import make_device
from radiowall.logging_setup import setup as setup_logging

log = logging.getLogger(__name__)

AMBER = (255, 176, 0)       # classic VFD color
AMBER_DIM = (110, 75, 0)    # separator / bg accents

SCROLL_PX_PER_FRAME = 2     # pixels per tick; smaller = slower, smoother

BUTTON_A_PIN = 23           # top button on the Pi TFT HAT
BUTTON_B_PIN = 24           # bottom button


def draw_mockup(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    pad = max(2, W // 64)

    # mock data that eventually comes from AppState
    top_line = "Vienna  AT  ·  #3 of 12"
    bottom_line = "vol 45  ·  94.0  ·  WiiM"
    scroll = "Radio Wien  ·  Blue in Green  ·  Miles Davis  ·  "

    with canvas(device) as draw:
        draw.text((pad, pad), top_line, font=fs.small, fill=AMBER)

        top_sep_y = int(H * 0.26)
        bot_sep_y = int(H * 0.74)
        draw.line((0, top_sep_y, W, top_sep_y), fill=AMBER_DIM)
        draw.line((0, bot_sep_y, W, bot_sep_y), fill=AMBER_DIM)

        band_top = top_sep_y + 2
        band_h = bot_sep_y - top_sep_y
        y_text = band_top + max(0, (band_h - fs.big.size) // 2)
        text_w = max(1, int(draw.textlength(scroll, font=fs.big)))
        offset_px = (frame * SCROLL_PX_PER_FRAME) % text_w
        draw.text((-offset_px, y_text), scroll, font=fs.big, fill=AMBER)
        draw.text((-offset_px + text_w, y_text), scroll, font=fs.big, fill=AMBER)

        draw.text((pad, bot_sep_y + pad), bottom_line, font=fs.small, fill=AMBER)


MODES = [draw_mockup, visualizer.draw]


class _Buttons:
    """Falling-edge detector for the 2 HAT buttons.

    Active-low with internal pull-up; a press is a high->low transition.
    No-ops gracefully if RPi.GPIO (or its lgpio shim) isn't importable.
    """

    def __init__(self) -> None:
        self._gpio = None
        self._last = (True, True)
        try:
            import RPi.GPIO as GPIO
        except ImportError:
            log.info("RPi.GPIO unavailable; button input disabled")
            return
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUTTON_A_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(BUTTON_B_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._gpio = GPIO
        log.info("buttons ready on GPIO %d/%d (active-low, pull-up)",
                 BUTTON_A_PIN, BUTTON_B_PIN)

    def poll(self) -> tuple[bool, bool]:
        """Return (a_pressed, b_pressed) as one-shot falling-edge events."""
        if self._gpio is None:
            return (False, False)
        a = bool(self._gpio.input(BUTTON_A_PIN))
        b = bool(self._gpio.input(BUTTON_B_PIN))
        a_event = self._last[0] and not a
        b_event = self._last[1] and not b
        self._last = (a, b)
        return (a_event, b_event)


def main() -> int:
    parser = argparse.ArgumentParser(description="RadioWall — Linux port")
    parser.add_argument("--emulate", action="store_true",
                        help="Force pygame emulator (also: RADIOWALL_EMULATE=1)")
    parser.add_argument("--scale", type=int, default=None,
                        help="Emulator window scale (default: 4)")
    args = parser.parse_args()

    setup_logging()
    log.info("radiowall starting")

    device = make_device(mock=args.emulate or None, scale=args.scale)
    log.info("display ready: %dx%d", device.width, device.height)
    fs = fonts.fonts_for(device.height)

    buttons = _Buttons()
    mode = 0

    try:
        frame = 0
        while True:
            a_event, b_event = buttons.poll()
            if a_event:
                mode = (mode + 1) % len(MODES)
                log.info("button A: mode -> %d (%s)", mode, MODES[mode].__name__)
            if b_event:
                mode = 0
                log.info("button B: reset to mockup")
            MODES[mode](device, frame, fs)
            frame += 1
            time.sleep(0.02)   # target 50 fps, actual capped by SPI+PNG
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
