"""Encoder push-button gesture detection: SHORT / LONG / DOUBLE /
VERY_LONG press.

Pure timing logic over debounced press edges — no hardware, fully
unit-testable with synthetic timestamps.

Semantics (one-encoder, "the longer you hold, the more drastic"):

- LONG   fires AT the 800 ms mark *while still held* — opens the menu
         without waiting for release. The following release is
         swallowed.
- VERY_LONG fires at the 3 s mark while still held — stop everything.
         LONG has necessarily fired at 800 ms on the way, so the menu
         visibly opens mid-hold and closes again when the stop lands;
         callers treat that as the expected ride.
- DOUBLE fires on the second press-down within 300 ms of the first
         release (the second release is swallowed).
- SHORT  fires 300 ms after a release, once a DOUBLE can no longer
         happen. The delay is invisible in practice: SHORT triggers
         NEXT, which starts a 1–3 s network round trip anyway.

Feed `update()` the edges from `RotaryEncoder.poll_events()` plus the
current time every frame (it needs plain time flow to fire LONG while
held and SHORT after the double-window closes).
"""

from __future__ import annotations

from enum import Enum

LONG_S = 0.800
DOUBLE_S = 0.300
VERY_LONG_S = 3.0


class Gesture(Enum):
    SHORT = "short"
    LONG = "long"
    DOUBLE = "double"
    VERY_LONG = "very_long"


class GestureDetector:
    def __init__(self, long_s: float = LONG_S, double_s: float = DOUBLE_S,
                 very_long_s: float = VERY_LONG_S):
        self._long_s = long_s
        self._double_s = double_s
        self._very_long_s = very_long_s
        self._down_at: float | None = None    # button currently held since
        self._long_fired = False              # LONG already emitted this hold
        self._very_fired = False              # VERY_LONG emitted this hold
        self._release_at: float | None = None # pending SHORT candidate

    def update(self, edges: list[tuple[float, bool]], now: float) -> list[Gesture]:
        """`edges` = [(timestamp, is_down), ...] since last call, oldest first."""
        out: list[Gesture] = []

        for ts, is_down in edges:
            if is_down:
                if (self._release_at is not None
                        and ts - self._release_at <= self._double_s):
                    out.append(Gesture.DOUBLE)
                    self._release_at = None
                    self._down_at = None      # swallow this press + its release
                    self._long_fired = True   # (reuse flag to eat the release)
                else:
                    self._down_at = ts
                    self._long_fired = False
                    self._very_fired = False
            else:                             # release
                if self._long_fired:
                    self._long_fired = False  # swallowed (post-LONG or post-DOUBLE)
                    self._down_at = None
                elif self._down_at is not None:
                    self._down_at = None
                    self._release_at = ts     # SHORT candidate, pending window

        # LONG: fires mid-hold at the deadline
        if (self._down_at is not None and not self._long_fired
                and now - self._down_at >= self._long_s):
            out.append(Gesture.LONG)
            self._long_fired = True

        # VERY_LONG: keep holding past LONG to reach the setup menu
        if (self._down_at is not None and not self._very_fired
                and now - self._down_at >= self._very_long_s):
            out.append(Gesture.VERY_LONG)
            self._very_fired = True

        # SHORT: release older than the double window with no second press
        if (self._release_at is not None
                and now - self._release_at > self._double_s):
            out.append(Gesture.SHORT)
            self._release_at = None

        return out
