"""Entry point — RadioWall: touch the map, hear that city's radio.

Inputs: IR touch frame (tap → play nearest city), one rotary encoder
(rotate = volume; short press = next station; long press = stop;
hold ≥3 s = setup menu; double press = cycle now-playing ↔ visualizer
screens), plus the dev HAT's two buttons (A = cycle screens, B = home)
where present. While setup is open the encoder and touch input belong
to the setup UI.

All network I/O runs on the RadioWorker thread; this loop only polls
inputs at ~50 Hz and renders from a state snapshot.

Legacy demo mode: RADIOWALL_AUDIO_PROXY=1 restores the old fixed-stream
proxy pipeline (RADIOWALL_STREAM_URL re-served at :8000/stream.mp3).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time

from radiowall import geo, places_db
from radiowall.audio import decoder, proxy
from radiowall.audio.hub import StreamHub
from radiowall.display import fonts, screens, visualizer
from radiowall.display.factory import make_device
from radiowall.display.setup_ui import SetupUI
from radiowall.input.encoder import RotaryEncoder
from radiowall.input.gestures import Gesture, GestureDetector
from radiowall.input.touch import TouchInput
from radiowall.logging_setup import setup as setup_logging
from radiowall.places_db import PlacesDB
from radiowall.radio import Next, PlayAt, RadioWorker, SetVolume, Stop
from radiowall.state import AppState

log = logging.getLogger(__name__)

BUTTON_A_PIN = 23
BUTTON_B_PIN = 24

DEFAULT_STREAM_URL = "http://ice1.somafm.com/groovesalad-128-mp3"
PROXY_PORT = 8000

# Screen 0 is the state-driven status screen; the rest are visualizers.
VISUALIZERS = [
    visualizer.draw_vfd,
    visualizer.draw_bars,
    visualizer.draw_mirror,
    visualizer.draw_radial,
    visualizer.draw_wave,
    visualizer.draw_scope,
    visualizer.draw_waterfall,
    visualizer.draw_vu,
]
NUM_SCREENS = 1 + len(VISUALIZERS)


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
    """Legacy fixed-stream demo mode (RADIOWALL_AUDIO_PROXY=1 only)."""
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

    # systemd stops us with SIGTERM; turn it into a clean exit so the
    # finally block below runs (and silences the WiiM on the way out).
    def _sigterm(_signo, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _sigterm)

    device = make_device(mock=args.emulate or None, scale=args.scale)
    log.info("display ready: %dx%d", device.width, device.height)
    fs = fonts.fonts_for(device.height)

    state = AppState()
    places = PlacesDB.load(places_db.default_path())
    log.info("places db: %d cities", len(places))
    calib = geo.load_calibration()

    legacy_proxy = os.getenv("RADIOWALL_AUDIO_PROXY", "").strip() == "1"
    hub = _start_audio_pipeline() if legacy_proxy else None
    worker = RadioWorker(state, places, use_decoder=not legacy_proxy)
    worker.start()

    buttons = _Buttons()
    encoder = RotaryEncoder()
    gestures = GestureDetector()
    touch = TouchInput()
    setup = SetupUI(worker)
    vol_step = int(os.getenv("RADIOWALL_VOL_STEP", "2"))
    screen = 0

    try:
        frame = 0
        fps_t = time.monotonic()
        fps_n = 0
        was_in_setup = False
        while True:
            now = time.monotonic()

            taps = touch.poll()
            if taps and setup.active:      # calibration wizard eats taps
                for t in taps:
                    setup.handle_tap(t.x, t.y)
            elif taps:                     # newest tap wins within a frame
                lat, lon = geo.tap_to_latlon(taps[-1].x, taps[-1].y, calib)
                log.info("tap (%.3f, %.3f) -> (%.2f, %.2f)",
                         taps[-1].x, taps[-1].y, lat, lon)
                worker.submit(PlayAt(lat, lon))

            delta, _presses = encoder.poll()
            if delta and setup.active:
                setup.handle_rotate(delta)
            elif delta:
                worker.submit(SetVolume(state.bump_volume(delta * vol_step)))

            for g in gestures.update(encoder.poll_events(), now):
                log.info("gesture: %s", g.name)
                if setup.active:
                    if g is Gesture.SHORT:
                        setup.handle_short()
                    elif g is Gesture.LONG:
                        setup.handle_long()
                    elif g is Gesture.DOUBLE:
                        setup.handle_double()
                elif g is Gesture.SHORT:
                    worker.submit(Next())
                elif g is Gesture.LONG:
                    worker.submit(Stop())
                elif g is Gesture.DOUBLE:
                    screen = (screen + 1) % NUM_SCREENS
                elif g is Gesture.VERY_LONG:
                    setup.open()
                    # reload calibration when setup closes (wizard may
                    # have rewritten it) — cheap enough to do every exit

            a_event, b_event = buttons.poll()
            if a_event and not setup.active:
                screen = (screen + 1) % NUM_SCREENS
            if b_event and not setup.active:
                screen = 0

            if setup.active:
                setup.draw(device, frame, fs)
                was_in_setup = True
            else:
                if was_in_setup:
                    calib = geo.load_calibration()
                    was_in_setup = False
                if screen == 0:
                    screens.draw_status_screen(device, frame, fs,
                                               state.snapshot())
                else:
                    VISUALIZERS[screen - 1](device, frame, fs)

            frame += 1
            fps_n += 1
            if now - fps_t >= 5.0:
                log.info("render: %.1f fps (screen=%d)",
                         fps_n / (now - fps_t), screen)
                fps_t = now
                fps_n = 0
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop(stop_playback=True)
        touch.stop()
        encoder.stop()
        decoder.stop()
        proxy.stop()
        if hub is not None:
            hub.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
