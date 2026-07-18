"""A handful of audio-reactive visualizers.

All of them read from radiowall.audio.decoder.get_bands() when a
stream is being decoded; otherwise they fall back to a sine source
so pressing Button A still shows motion.

Each `draw_*` function is independently callable from main's MODES
list — the fps logger names the active mode so you can see
per-visualizer performance directly in the log stream.

Modes: vfd (segmented bars + peak hold), bars, mirror, radial, wave,
scope (real waveform), waterfall (scrolling spectrogram), vu (analog
needle meter).
"""

from __future__ import annotations

import math
import time

from PIL import Image, ImageDraw
from luma.core.render import canvas

from radiowall.audio import decoder
from radiowall.display import fonts

AMBER = (255, 176, 0)
AMBER_BRIGHT = (255, 210, 80)
AMBER_DIM = (110, 75, 0)
AMBER_GHOST = (60, 40, 0)

NUM_BARS = decoder.NUM_BANDS
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


def _amber(a: float) -> tuple[int, int, int]:
    """Amber scaled by brightness 0..1 (grayscale panels map it down)."""
    a = max(0.0, min(1.0, a))
    return (int(255 * a), int(176 * a), 0)


# ---------- 1. VFD segmented bars with peak-hold caps ------------------

_SEG_H = 4                     # 3 px lit + 1 px gap
_PEAK_HOLD_S = 0.55
_PEAK_FALL_SEGS_PER_S = 14.0

_vfd_peak = [0.0] * NUM_BARS   # cap position, in segment units
_vfd_hold = [0.0] * NUM_BARS   # monotonic time until which the cap holds


def draw_vfd(device, frame: int, fs: fonts.FontSet) -> None:
    """Classic hi-fi spectrum analyzer: segmented bars, falling caps."""
    W, H = device.width, device.height
    nsegs = H // _SEG_H
    levels = _levels(frame)
    now = time.monotonic()

    bar_slot = W / NUM_BARS
    bar_w = max(3, int(bar_slot * 0.68))
    gap = (bar_slot - bar_w) / 2

    with canvas(device) as draw:
        for i, amp in enumerate(levels):
            lit = int(amp * nsegs + 0.5)
            x = int(i * bar_slot + gap)

            # peak cap: jump up with the bar, hold, then fall
            if lit >= _vfd_peak[i]:
                _vfd_peak[i] = float(lit)
                _vfd_hold[i] = now + _PEAK_HOLD_S
            elif now > _vfd_hold[i]:
                _vfd_peak[i] = max(
                    float(lit),
                    _vfd_peak[i] - _PEAK_FALL_SEGS_PER_S / 45.0)

            for s in range(nsegs):
                y = H - (s + 1) * _SEG_H
                if s < lit:
                    color = AMBER_BRIGHT if s >= nsegs - 3 else AMBER
                    draw.rectangle(
                        (x, y, x + bar_w, y + _SEG_H - 2), fill=color)
                else:
                    # unlit segment ghost — the phosphor-grid VFD look
                    draw.rectangle(
                        (x, y + 1, x + bar_w, y + 1), fill=AMBER_GHOST)

            cap = int(_vfd_peak[i])
            if cap > lit and cap > 0:
                y = H - cap * _SEG_H
                draw.rectangle((x, y, x + bar_w, y + 1), fill=AMBER_BRIGHT)


# ---------- 2. Symmetric vertical bars --------------------------------

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


# ---------- 3. Mirror bars meeting in the middle ----------------------

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


# ---------- 4. Radial bars from center --------------------------------

def draw_radial(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    cx, cy = W // 2, H // 2
    inner = min(W, H) * 0.12
    outer_max = min(W, H) * 0.48
    # twelve angular slots regardless of band count
    slots = 12
    levels = _levels(frame)
    # sample bands to fill the slots
    radial_levels = [levels[(i * NUM_BARS) // slots] for i in range(slots)]
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


# ---------- 5. Smooth line / spectrum curve ---------------------------

def draw_wave(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    baseline = int(H * 0.75)
    amp_max = int(H * 0.60)
    levels = _levels(frame)

    # interpolate NUM_BARS points to a denser polyline across the width
    # so the curve looks smooth instead of hard segments
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


# ---------- 6. Oscilloscope (real waveform) ---------------------------

_scope_gain = 0.05             # running peak for auto-gain


def draw_scope(device, frame: int, fs: fonts.FontSet) -> None:
    global _scope_gain
    W, H = device.width, device.height
    cy = H // 2

    wave = decoder.get_wave(W)
    if not wave:
        # synthetic idle trace
        wave = [
            0.5 * math.sin(x * 0.06 + frame * 0.25)
            + 0.22 * math.sin(x * 0.15 - frame * 0.4)
            for x in range(W)
        ]

    peak = max(0.02, max(abs(v) for v in wave))
    _scope_gain = max(peak, _scope_gain * 0.985)
    scale = (H / 2 - 3) / _scope_gain

    n = len(wave)
    pts = [
        (int(i * (W - 1) / max(1, n - 1)), cy - int(v * scale))
        for i, v in enumerate(wave)
    ]

    with canvas(device) as draw:
        draw.line((0, cy, W, cy), fill=AMBER_GHOST)
        # dim halo under the trace for a phosphor-glow feel
        draw.line(pts, fill=AMBER_DIM, width=3)
        draw.line(pts, fill=AMBER_BRIGHT, width=1)


# ---------- 7. Scrolling spectrogram / waterfall -----------------------

_WF_SCROLL_PX = 2              # px per render frame (~80 px/s at 40 fps)
_wf_img: Image.Image | None = None


def draw_waterfall(device, frame: int, fs: fonts.FontSet) -> None:
    """Time scrolls left; low frequencies at the bottom, brightness =
    band level. Keeps its own persistent image and blits it directly."""
    global _wf_img
    W, H = device.width, device.height
    if _wf_img is None or _wf_img.size != (W, H):
        _wf_img = Image.new(device.mode, (W, H), "black")
    img = _wf_img

    img.paste(img.crop((_WF_SCROLL_PX, 0, W, H)), (0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((W - _WF_SCROLL_PX, 0, W - 1, H - 1), fill="black")

    levels = _levels(frame)
    band_h = H / NUM_BARS
    x0, x1 = W - _WF_SCROLL_PX, W - 1
    for i, amp in enumerate(levels):
        if amp < 0.05:
            continue
        y_top = H - 1 - int((i + 1) * band_h) + 1
        y_bot = H - 1 - int(i * band_h)
        # strong gamma: quiet bands stay near-black so beats read as
        # bright streaks instead of a washed-out amber field
        d.rectangle((x0, y_top, x1, y_bot), fill=_amber(amp ** 1.7))

    device.display(img)


# ---------- 8. Analog VU needle meter ----------------------------------

_vu_shown = 0.0
_vu_ref = 0.05                 # running RMS peak for normalization
_vu_t = 0.0
_VU_ATTACK_S = 0.06
_VU_RELEASE_S = 0.50


def draw_vu(device, frame: int, fs: fonts.FontSet) -> None:
    global _vu_shown, _vu_ref, _vu_t
    W, H = device.width, device.height

    rms = decoder.get_rms()
    if rms is None:
        rms = 0.28 + 0.24 * math.sin(frame * 0.06) \
            + 0.10 * math.sin(frame * 0.23)
    _vu_ref = max(rms, _vu_ref * 0.999, 0.02)
    target = min(1.0, rms / _vu_ref)

    # VU ballistics: quick rise, slow fall
    now = time.monotonic()
    dt = min(0.1, now - _vu_t) if _vu_t else 0.02
    _vu_t = now
    tau = _VU_ATTACK_S if target > _vu_shown else _VU_RELEASE_S
    _vu_shown += (target - _vu_shown) * min(1.0, dt / tau)

    # needle geometry: pivot below the bottom edge, sweep ±50° from up
    px, py = W // 2, H + 26
    r = py - 6                 # needle tip reaches y=6 at center
    sweep = 50.0

    with canvas(device) as draw:
        # scale ticks
        for t in range(11):
            a = math.radians(-sweep + t * (2 * sweep / 10))
            sin_a, cos_a = math.sin(a), math.cos(a)
            r2 = r + 2
            r1 = r2 - (7 if t % 5 == 0 else 4)
            color = AMBER if t >= 8 else AMBER_DIM
            draw.line(
                (px + r1 * sin_a, py - r1 * cos_a,
                 px + r2 * sin_a, py - r2 * cos_a),
                fill=color, width=2 if t >= 8 else 1)
        # arc under the ticks
        bbox = (px - r + 9, py - r + 9, px + r - 9, py + r - 9)
        draw.arc(bbox, 270 - sweep, 270 + sweep, fill=AMBER_GHOST)

        # needle
        a = math.radians(-sweep + _vu_shown * 2 * sweep)
        sin_a, cos_a = math.sin(a), math.cos(a)
        draw.line(
            (px + 14 * sin_a, py - 14 * cos_a,
             px + (r - 2) * sin_a, py - (r - 2) * cos_a),
            fill=AMBER_BRIGHT, width=2)

        # peak lamp (top right)
        lamp = (W - 16, 6, W - 8, 14)
        if _vu_shown > 0.88:
            draw.ellipse(lamp, fill=AMBER_BRIGHT)
        else:
            draw.ellipse(lamp, outline=AMBER_GHOST)

        draw.text((8, 4), "VU", font=fs.small, fill=AMBER_DIM)


# Back-compat alias (old main.py imports `visualizer.draw`)
draw = draw_bars
