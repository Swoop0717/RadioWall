"""Encoder push-button gesture detection: SHORT / DOUBLE / TRIPLE /
LONG / VERY_LONG press.

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
- TRIPLE fires immediately on the third press-down of a quick chain
         (favorite the current station); its release is swallowed.
- DOUBLE fires 300 ms after the second release, once a TRIPLE can no
         longer happen.
- SHORT  fires 300 ms after a lone release, once a DOUBLE can no
         longer happen. The delays are invisible in practice: SHORT
         triggers NEXT (a 1-3 s network round trip), DOUBLE cycles
         cosmetic screens.

Feed `update()` the edges from `RotaryEncoder.poll_events()` plus the
current time every frame (it needs plain time flow to fire the hold
gestures and to resolve press chains).
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
    TRIPLE = "triple"
    VERY_LONG = "very_long"


class GestureDetector:
    def __init__(self, long_s: float = LONG_S, double_s: float = DOUBLE_S,
                 very_long_s: float = VERY_LONG_S):
        self._long_s = long_s
        self._double_s = double_s
        self._very_long_s = very_long_s
        self._down_at: float | None = None    # button currently held since
        self._long_fired = False              # LONG emitted this hold
        self._very_fired = False              # VERY_LONG emitted this hold
        self._swallow_release = False         # next release is TRIPLE's
        self._chain = 0                       # quick presses released so far
        self._chain_release = 0.0             # ts of the chain's last release

    def update(self, edges: list[tuple[float, bool]], now: float) -> list[Gesture]:
        """`edges` = [(timestamp, is_down), ...] since last call, oldest first."""
        out: list[Gesture] = []

        for ts, is_down in edges:
            if is_down:
                if (self._chain > 0
                        and ts - self._chain_release <= self._double_s):
                    if self._chain == 2:      # third quick press
                        out.append(Gesture.TRIPLE)
                        self._chain = 0
                        self._swallow_release = True
                        self._down_at = None  # a held 3rd press stays inert
                    else:
                        self._down_at = ts
                else:                         # fresh chain
                    if self._chain > 0:
                        # previous chain expired between polls — resolve
                        # it before it's forgotten
                        out.append(Gesture.SHORT if self._chain == 1
                                   else Gesture.DOUBLE)
                    self._chain = 0
                    self._down_at = ts
                    self._long_fired = False
                    self._very_fired = False
                    self._swallow_release = False
            else:                             # release
                if self._swallow_release or self._long_fired:
                    self._swallow_release = False
                    self._long_fired = False
                    self._down_at = None
                    self._chain = 0
                elif self._down_at is not None:
                    self._down_at = None
                    self._chain += 1
                    self._chain_release = ts

        # hold gestures: only on a held FIRST press (not mid-chain)
        if self._down_at is not None and self._chain == 0:
            if (not self._long_fired
                    and now - self._down_at >= self._long_s):
                out.append(Gesture.LONG)
                self._long_fired = True
            if (self._long_fired and not self._very_fired
                    and now - self._down_at >= self._very_long_s):
                out.append(Gesture.VERY_LONG)
                self._very_fired = True

        # chain resolution: no further press arrived inside the window
        if (self._chain > 0 and self._down_at is None
                and now - self._chain_release > self._double_s):
            out.append(Gesture.SHORT if self._chain == 1 else Gesture.DOUBLE)
            self._chain = 0

        return out
