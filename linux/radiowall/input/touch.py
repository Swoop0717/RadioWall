"""IR touch frame input (USB HID, evdev).

The 55" CVTouch/IrScreen frame (VID 1FF7, PID 0013) exposes three input
interfaces; the useful one is the absolute-pointer "Mouse" interface
(`IrScreen cc Mouse`): BTN_LEFT down/up per touch plus ABS_X/ABS_Y in
0..32767 — the same coordinate space the ESP32 firmware consumed. The
"Touchscreen"-named interface stays silent on this firmware.

A background thread reads events; the render loop drains completed taps
via `poll()`. Coordinates are normalized to 0.0..1.0 so callers never
see the raw 15-bit space.

If no matching device exists (dev laptop, frame unplugged) the reader is
inert and `poll()` returns [] — same convention as RotaryEncoder.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

try:
    from evdev import InputDevice, ecodes, list_devices
    _HAVE_EVDEV = True
except ImportError:
    _HAVE_EVDEV = False

_DEVICE_NAME_HINT = "IrScreen"
_ABS_MAX = 32767

# Ghost-touch rejection. The IR beam plane sits a few mm above the map,
# so a forearm reaching across, a sleeve or a leaning body all produce
# down/up cycles — but they MOVE through the plane, while a deliberate
# fingertip stays put. Field data (Seoul test, 2026-07-19): real tap
# traveled <0.01 normalized; arm ghosts landed at frame edges after
# sweeping. Contacts that travel too far or are impossibly brief get
# dropped.
_MAX_TAP_TRAVEL = 0.04         # normalized (~4.4 cm on a 110 cm frame)
_MIN_TAP_S = 0.02              # shorter = beam flicker, not a finger


@dataclass(frozen=True)
class Tap:
    """One completed touch, normalized to 0.0..1.0 (top-left origin)."""
    x: float
    y: float


def _find_device():
    """The IrScreen interface that actually emits touches (has BTN_LEFT)."""
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        keys = dev.capabilities().get(ecodes.EV_KEY, [])
        if _DEVICE_NAME_HINT in dev.name and ecodes.BTN_LEFT in keys:
            return dev
        dev.close()
    return None


class TouchInput:
    """Reads the IR frame on a daemon thread; drain taps via `poll()`.

    A tap is reported on finger-up, with the last position seen while
    down. Dragging is collapsed into its release point — station picking
    is point-and-lift, not gestures.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._taps: list[Tap] = []
        self._dev = None
        self._running = False
        # tap-assembly state (driven by _on_event; separate from the
        # reader thread so the logic is unit-testable without evdev)
        self._x = self._y = 0
        self._down = False
        self._down_t = 0.0
        self._down_x = self._down_y = 0
        self._travel = 0

        if not _HAVE_EVDEV:
            log.info("evdev unavailable; touch input disabled")
            return
        dev = _find_device()
        if dev is None:
            log.info("no IR touch frame found; touch input disabled")
            return

        self._dev = dev
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="touch",
                                        daemon=True)
        self._thread.start()
        log.info("touch frame ready: %s (%s)", dev.name, dev.path)

    def _loop(self) -> None:
        try:
            for ev in self._dev.read_loop():
                if not self._running:
                    break
                if ev.type == ecodes.EV_ABS:
                    self._on_event("abs_x" if ev.code == ecodes.ABS_X
                                   else "abs_y" if ev.code == ecodes.ABS_Y
                                   else "", ev.value, time.monotonic())
                elif ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_LEFT:
                    self._on_event("btn", ev.value, time.monotonic())
        except OSError as e:
            log.warning("touch frame read failed (%s); touch disabled", e)

    def _on_event(self, kind: str, value: int, now: float) -> None:
        """Assemble taps from raw events; rejects plane-crossing ghosts."""
        if kind == "abs_x":
            self._x = value
            if self._down:
                self._travel = max(self._travel, abs(value - self._down_x))
        elif kind == "abs_y":
            self._y = value
            if self._down:
                self._travel = max(self._travel, abs(value - self._down_y))
        elif kind == "btn":
            if value:
                self._down = True
                self._down_t = now
                self._down_x, self._down_y = self._x, self._y
                self._travel = 0
            elif self._down:
                self._down = False
                duration = now - self._down_t
                travel = self._travel / _ABS_MAX
                if travel > _MAX_TAP_TRAVEL:
                    log.info("ghost touch rejected: traveled %.2f in %.0f ms "
                             "(arm/sleeve crossing the beam plane?)",
                             travel, duration * 1000)
                    return
                if duration < _MIN_TAP_S:
                    log.info("ghost touch rejected: %.0f ms blip",
                             duration * 1000)
                    return
                tap = Tap(self._x / _ABS_MAX, self._y / _ABS_MAX)
                with self._lock:
                    self._taps.append(tap)

    def poll(self) -> list[Tap]:
        """Drain and return taps completed since the last call."""
        with self._lock:
            taps, self._taps = self._taps, []
        return taps

    def stop(self) -> None:
        self._running = False
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass


def _smoketest() -> None:
    """`python -m radiowall.input.touch` — print taps to stdout."""
    import time

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    touch = TouchInput()
    if touch._dev is None:
        print("No touch frame here.")
        return
    print("Touch the frame. Ctrl+C to stop.")
    try:
        while True:
            for tap in touch.poll():
                print(f"TAP  x={tap.x:.3f}  y={tap.y:.3f}")
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        touch.stop()


if __name__ == "__main__":
    _smoketest()
