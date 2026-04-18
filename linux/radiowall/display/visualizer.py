"""EQ-style visualizer — real bands when audio is flowing, sine when not.

Reads smoothed FFT band levels from radiowall.audio.decoder. If the
decoder isn't running (no stream URL, ffmpeg missing, etc.), falls
back to the phase-shifted sine demo so the screen isn't dead when
you hit Button A.
"""

from __future__ import annotations

import math

from luma.core.render import canvas

from radiowall.audio import decoder
from radiowall.display import fonts

AMBER = (255, 176, 0)
AMBER_DIM = (110, 75, 0)

NUM_BARS = 8
SINE_SPEED = 0.12
SINE_SPREAD = 0.55


def _sine_levels(frame: int) -> list[float]:
    return [
        abs(math.sin(frame * SINE_SPEED + i * SINE_SPREAD)) ** 1.5
        for i in range(NUM_BARS)
    ]


def draw(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    cy = H // 2
    max_half_h = int(H * 0.42)

    bands = decoder.get_bands()
    if bands is None:
        levels = _sine_levels(frame)
    else:
        # decoder may have a different NUM_BANDS; stretch/truncate
        if len(bands) >= NUM_BARS:
            levels = bands[:NUM_BARS]
        else:
            levels = bands + [0.0] * (NUM_BARS - len(bands))

    bar_slot = W / NUM_BARS
    bar_w = max(3, int(bar_slot * 0.6))
    gap = (bar_slot - bar_w) / 2

    with canvas(device) as draw_ctx:
        for i, amp in enumerate(levels):
            half_h = max(2, int(max_half_h * amp))
            x = int(i * bar_slot + gap)
            y1 = cy - half_h
            y2 = cy + half_h
            draw_ctx.rectangle((x, y1, x + bar_w, y2), fill=AMBER)

            draw_ctx.rectangle(
                (x, cy - max_half_h, x + bar_w, cy - max_half_h + 1),
                fill=AMBER_DIM,
            )
            draw_ctx.rectangle(
                (x, cy + max_half_h - 1, x + bar_w, cy + max_half_h),
                fill=AMBER_DIM,
            )
