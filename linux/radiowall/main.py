"""Entry point — VFD-style mockup + visualizer, button-togglable.

On startup, if RADIOWALL_STREAM_URL is set, the Pi fetches that
stream once and:
  - serves it at http://<pi>:8000/stream.mp3 (for the WiiM to play)
  - decodes + FFTs a copy for the reactive visualizer
See radiowall.audio for the stream hub/decoder/proxy.
"""

from __future__ import annotations

import argparse
import logging
import os
import time

from luma.core.render import canvas

from radiowall.audio import decoder, proxy
from radiowall.audio.hub import StreamHub
from radiowall.display import fonts, visualizer
from radiowall.display.factory import make_device
from radiowall.input.encoder import RotaryEncoder
from radiowall.logging_setup import setup as setup_logging

log = logging.getLogger(__name__)

AMBER = (255, 176, 0)
AMBER_DIM = (110, 75, 0)

SCROLL_PX_PER_FRAME = 2
BUTTON_A_PIN = 23
BUTTON_B_PIN = 24

DEFAULT_STREAM_URL = "http://ice1.somafm.com/groovesalad-128-mp3"
PROXY_PORT = 8000


def draw_mockup(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    pad = max(2, W // 64)

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


MODES = [
    draw_mockup,
    visualizer.draw_bars,
    visualizer.draw_mirror,
    visualizer.draw_radial,
    visualizer.draw_wave,
]


class _Buttons:
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
        if self._gpio is None:
            return (False, False)
        a = bool(self._gpio.input(BUTTON_A_PIN))
        b = bool(self._gpio.input(BUTTON_B_PIN))
        a_event = self._last[0] and not a
        b_event = self._last[1] and not b
        self._last = (a, b)
        return (a_event, b_event)


def _start_audio_pipeline() -> StreamHub | None:
    url = os.getenv("RADIOWALL_STREAM_URL", DEFAULT_STREAM_URL).strip()
    if not url or url.lower() == "off":
        log.info("audio pipeline disabled (RADIOWALL_STREAM_URL=off)")
        return None

    hub = StreamHub(url)
    hub.start()
    proxy.start(hub, port=PROXY_PORT)
    decoder.start(url)
    return hub


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
    encoder = RotaryEncoder()
    hub = _start_audio_pipeline()
    mode = 0

    try:
        frame = 0
        fps_t = time.monotonic()
        fps_n = 0
        while True:
            a_event, b_event = buttons.poll()
            delta, presses = encoder.poll()
            if a_event:
                mode = (mode + 1) % len(MODES)
                log.info("button A: mode -> %d (%s)", mode, MODES[mode].__name__)
            if delta:
                mode = (mode + delta) % len(MODES)
                log.info("encoder: mode -> %d (%s)", mode, MODES[mode].__name__)
            if b_event or presses:
                mode = 0
                log.info("%s: reset to mockup",
                         "button B" if b_event else "encoder press")
            MODES[mode](device, frame, fs)
            frame += 1
            fps_n += 1
            now = time.monotonic()
            if now - fps_t >= 2.0:
                log.info("render: %.1f fps (mode=%s)",
                         fps_n / (now - fps_t), MODES[mode].__name__)
                fps_t = now
                fps_n = 0
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        encoder.stop()
        decoder.stop()
        proxy.stop()
        if hub is not None:
            hub.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
