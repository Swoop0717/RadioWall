"""Tap assembly + ghost rejection in the IR frame driver — pure event
feeding, no evdev needed."""

from radiowall.input.touch import _ABS_MAX, TouchInput


def _mk():
    t = TouchInput()          # no device on the dev machine → inert reader
    assert t._dev is None
    return t


def _norm(v):
    return int(v * _ABS_MAX)


def test_clean_tap_passes():
    t = _mk()
    t._on_event("abs_x", _norm(0.848), 0.0)
    t._on_event("abs_y", _norm(0.257), 0.0)
    t._on_event("btn", 1, 0.0)
    t._on_event("abs_x", _norm(0.850), 0.05)   # 2px of finger wobble
    t._on_event("btn", 0, 0.12)
    taps = t.poll()
    assert len(taps) == 1
    assert abs(taps[0].x - 0.850) < 0.001


def test_arm_sweep_rejected():
    """Forearm crosses the beam plane: big travel between down and up."""
    t = _mk()
    t._on_event("abs_x", _norm(0.85), 0.0)
    t._on_event("abs_y", _norm(0.30), 0.0)
    t._on_event("btn", 1, 0.0)
    t._on_event("abs_x", _norm(0.10), 0.2)     # swept to the frame edge
    t._on_event("abs_y", _norm(0.60), 0.2)
    t._on_event("btn", 0, 0.3)
    assert t.poll() == []


def test_beam_flicker_rejected():
    t = _mk()
    t._on_event("abs_x", _norm(0.5), 0.0)
    t._on_event("abs_y", _norm(0.5), 0.0)
    t._on_event("btn", 1, 0.000)
    t._on_event("btn", 0, 0.005)               # 5 ms — not a finger
    assert t.poll() == []


def test_two_taps_independent_travel():
    t = _mk()
    # ghost first
    t._on_event("btn", 1, 0.0)
    t._on_event("abs_x", _norm(0.9), 0.1)
    t._on_event("btn", 0, 0.2)
    # then a clean tap — travel counter must have reset
    t._on_event("abs_x", _norm(0.3), 1.0)
    t._on_event("abs_y", _norm(0.4), 1.0)
    t._on_event("btn", 1, 1.0)
    t._on_event("btn", 0, 1.1)
    taps = t.poll()
    assert len(taps) == 1
    assert abs(taps[0].x - 0.3) < 0.001
