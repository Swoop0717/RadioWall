"""Rotary encoder (EC11 / KY-040) input on GPIO.

Reads quadrature rotation + a debounced push-switch on a background thread,
so the main render loop (which only ticks ~50 Hz) never misses fast turns.
Call `poll()` each frame to drain accumulated rotation steps and presses.

Proven wiring on the Pi 3 B+ dev rig — a KY-040 with the `+` pin left
unconnected, relying on internal pull-ups (all the 3.3 V header pins sit
under the ST7789 HAT). Identical physical pins on the Orange Pi Zero 3W;
the per-board GPIO numbers + library come from `radiowall.hw.board`:

    KY-040    physical pin   Pi BCM    OPi Zero3W line
    ------    ------------   ------    ---------------
    CLK       40             GPIO21    39  (PB7)
    DT        38             GPIO20    40  (PB8)
    SW        36             GPIO16    98  (PD2)
    GND       39             —         —
    +         (leave unwired)

The switch read uses a debounce **plus a rotation guard**: while the dial is
actively turning, the debounce timer keeps resetting, so electrical coupling
from the rotation lines can never hold long enough to register as a press.

> Caveat learned the hard way: a *cheap/worn* KY-040 can emit **real** switch
> closures while you turn it (the shaft mechanically tickles its own button).
> That's a genuine contact event no software filter can or should remove —
> replace the encoder. Rotation reading is unaffected.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

from radiowall.hw.board import get_gpio, get_profile


@dataclass(frozen=True)
class EncoderPins:
    """GPIO numbers in the board's native scheme (BCM on the Pi, gpiochip
    line offsets on the Orange Pi). Same physical pins 40/38/36 either way;
    None → take the number from the board profile."""
    clk: int | None = None   # physical pin 40
    dt: int | None = None    # physical pin 38
    sw: int | None = None    # physical pin 36


class RotaryEncoder:
    """Polls an EC11/KY-040 on a daemon thread; drain via `poll()`.

    `poll()` returns `(delta, presses)`:
      - `delta`   net rotation steps since the last poll (+ = clockwise),
      - `presses` number of debounced button presses since the last poll.

    If `RPi.GPIO` is unavailable (e.g. on a dev laptop) the encoder is inert
    and `poll()` always returns `(0, 0)` — callers need no platform guard.
    """

    def __init__(self, pins: EncoderPins | None = None, *,
                 debounce_s: float = 0.030, reverse: bool = False,
                 poll_interval_s: float = 0.0008) -> None:
        profile = get_profile()
        pins = pins or EncoderPins()
        self.pins = EncoderPins(
            clk=pins.clk if pins.clk is not None else profile.encoder_clk,
            dt=pins.dt if pins.dt is not None else profile.encoder_dt,
            sw=pins.sw if pins.sw is not None else profile.encoder_sw,
        )
        self.debounce_s = debounce_s
        self.reverse = reverse
        self.poll_interval_s = poll_interval_s

        self._lock = threading.Lock()
        self._delta = 0
        self._presses = 0
        self._gpio = None
        self._running = False

        GPIO = get_gpio()
        if GPIO is None:
            log.info("no GPIO backend on this host; rotary encoder disabled")
            return

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        for p in (self.pins.clk, self.pins.dt, self.pins.sw):
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._gpio = GPIO
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="encoder",
                                         daemon=True)
        self._thread.start()
        log.info("rotary encoder on GPIO clk=%d dt=%d sw=%d (internal pull-ups)",
                 self.pins.clk, self.pins.dt, self.pins.sw)

    def _loop(self) -> None:
        g = self._gpio
        clk_pin, dt_pin, sw_pin = self.pins.clk, self.pins.dt, self.pins.sw
        last_clk = g.input(clk_pin)
        sw_state = 1
        sw_cand = g.input(sw_pin)
        sw_cand_t = time.monotonic()

        while self._running:
            now = time.monotonic()
            clk = g.input(clk_pin)
            if clk != last_clk and clk == 0:           # falling edge of CLK
                step = 1 if g.input(dt_pin) != clk else -1
                if self.reverse:
                    step = -step
                with self._lock:
                    self._delta += step
                # rotation guard: don't let the switch confirm mid-turn
                sw_cand = sw_state
                sw_cand_t = now
            last_clk = clk

            raw = g.input(sw_pin)
            if raw != sw_cand:
                sw_cand = raw
                sw_cand_t = now
            elif now - sw_cand_t >= self.debounce_s and sw_cand != sw_state:
                sw_state = sw_cand
                if sw_state == 0:                      # active-low: pressed
                    with self._lock:
                        self._presses += 1
            time.sleep(self.poll_interval_s)

    def poll(self) -> tuple[int, int]:
        """Drain and return `(delta, presses)` accumulated since last call."""
        with self._lock:
            d, p = self._delta, self._presses
            self._delta = 0
            self._presses = 0
        return d, p

    def stop(self) -> None:
        self._running = False
        if self._gpio is not None:
            try:
                self._gpio.cleanup((self.pins.clk, self.pins.dt, self.pins.sw))
            except Exception:
                pass


def _smoketest() -> None:
    """`python -m radiowall.input.encoder` — print rotation/press to stdout.

    The quickest way to validate a (replacement) encoder + its wiring without
    touching the display. Ctrl+C to quit.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    enc = RotaryEncoder()
    if enc._gpio is None:
        print("No GPIO here — run this on the Pi.")
        return
    print("Turn the knob / press it. Ctrl+C to stop.")
    pos = 0
    try:
        while True:
            delta, presses = enc.poll()
            if delta:
                pos += delta
                print(f"{'CW' if delta > 0 else 'CCW'}  pos={pos}")
            for _ in range(presses):
                print("PRESS")
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        enc.stop()


if __name__ == "__main__":
    _smoketest()
