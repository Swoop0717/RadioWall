"""A handful of audio-reactive visualizers.

All of them read from radiowall.audio.decoder.get_bands() when a
stream is being decoded; otherwise they fall back to a sine source
so pressing Button A still shows motion.

Each `draw_*` function is independently callable from main's MODES
list — the fps logger names the active mode so you can see
per-visualizer performance directly in the log stream.
"""

from __future__ import annotations

import math

from luma.core.render import canvas

from radiowall.audio import decoder
from radiowall.display import fonts

AMBER = (255, 176, 0)
AMBER_BRIGHT = (255, 210, 80)
AMBER_DIM = (110, 75, 0)
AMBER_GHOST = (60, 40, 0)

NUM_BARS = 8
SINE_SPEED = 0.12
SINE_SPREAD = 0.55


def _sine_levels(frame: int) -> list[float]:
    return [
        abs(math.sin(frame * SINE_SPEED + i * SINE_SPREAD)) ** 1.5
        for i in range(NUM_BARS)
    ]


# FFT bands update at ~43 Hz while the panel renders at 30-45 fps; drawing
# the raw values makes bars jump in visible steps. Glide the *displayed*
# level toward the target each render frame instead.
_shown = [0.0] * NUM_BARS
_LERP = 0.45


def _levels(frame: int) -> list[float]:
    bands = decoder.get_bands()
    if bands is None:
        return _sine_levels(frame)
    if len(bands) < NUM_BARS:
        bands = bands + [0.0] * (NUM_BARS - len(bands))
    for i in range(NUM_BARS):
        _shown[i] += (bands[i] - _shown[i]) * _LERP
    return list(_shown)


# ---------- 1. Symmetric vertical bars --------------------------------

def draw_bars(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    cy = H // 2
    max_half_h = int(H * 0.42)
    levels = _levels(frame)

    bar_slot = W / NUM_BARS
    bar_w = max(3, int(bar_slot * 0.6))
    gap = (bar_slot - bar_w) / 2

    with canvas(device) as draw:
        for i, amp in enumerate(levels):
            half_h = max(2, int(max_half_h * amp))
            x = int(i * bar_slot + gap)
            draw.rectangle(
                (x, cy - half_h, x + bar_w, cy + half_h), fill=AMBER)
            draw.rectangle(
                (x, cy - max_half_h, x + bar_w, cy - max_half_h + 1),
                fill=AMBER_DIM)
            draw.rectangle(
                (x, cy + max_half_h - 1, x + bar_w, cy + max_half_h),
                fill=AMBER_DIM)


# ---------- 2. Mirror bars meeting in the middle ----------------------

def draw_mirror(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    levels = _levels(frame)
    bar_slot = W / NUM_BARS
    bar_w = max(3, int(bar_slot * 0.7))
    gap = (bar_slot - bar_w) / 2
    mid_gap = 4
    max_h = (H - mid_gap) // 2

    with canvas(device) as draw:
        for i, amp in enumerate(levels):
            bar_h = max(2, int(max_h * amp))
            x = int(i * bar_slot + gap)
            # top bar grows downward from the top edge
            draw.rectangle((x, 0, x + bar_w, bar_h), fill=AMBER)
            # bottom bar grows upward from the bottom edge
            draw.rectangle(
                (x, H - bar_h, x + bar_w, H), fill=AMBER_BRIGHT)


# ---------- 3. Radial bars from center --------------------------------

def draw_radial(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    cx, cy = W // 2, H // 2
    inner = min(W, H) * 0.12
    outer_max = min(W, H) * 0.48
    # twelve angular slots for more visual density than 8
    slots = 12
    levels = _levels(frame)
    # repeat/sample bands to fill 12 slots
    radial_levels = [levels[i % NUM_BARS] for i in range(slots)]
    # slow spin so static values aren't rigid
    spin = (frame * 0.015) % (2 * math.pi)

    with canvas(device) as draw:
        for i, amp in enumerate(radial_levels):
            angle = i * 2 * math.pi / slots + spin
            r1 = inner
            r2 = inner + (outer_max - inner) * amp
            x1 = cx + r1 * math.cos(angle)
            y1 = cy + r1 * math.sin(angle)
            x2 = cx + r2 * math.cos(angle)
            y2 = cy + r2 * math.sin(angle)
            draw.line((x1, y1, x2, y2), fill=AMBER, width=3)
        # soft center disc
        draw.ellipse(
            (cx - inner + 2, cy - inner + 2, cx + inner - 2, cy + inner - 2),
            outline=AMBER_DIM, width=1,
        )


# ---------- 4. Smooth line / waveform ---------------------------------

def draw_wave(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    baseline = int(H * 0.75)
    amp_max = int(H * 0.60)
    levels = _levels(frame)

    # interpolate NUM_BARS points to a denser polyline across the width
    # so the curve looks smooth instead of 8 hard segments
    density = 4
    n = (NUM_BARS - 1) * density + 1
    xs = [int(i * (W - 1) / (n - 1)) for i in range(n)]
    ys: list[int] = []
    for i in range(n):
        pos = i / density
        lo = int(pos)
        hi = min(NUM_BARS - 1, lo + 1)
        frac = pos - lo
        v = levels[lo] * (1 - frac) + levels[hi] * frac
        ys.append(baseline - int(v * amp_max))

    with canvas(device) as draw:
        # baseline reference
        draw.line((0, baseline, W, baseline), fill=AMBER_GHOST)
        # filled area under curve — a series of thin vertical lines
        for x, y in zip(xs, ys):
            draw.line((x, y, x, baseline), fill=AMBER_DIM)
        # the curve itself
        points = list(zip(xs, ys))
        draw.line(points, fill=AMBER, width=2)


# Back-compat alias (old main.py imports `visualizer.draw`)
draw = draw_bars
