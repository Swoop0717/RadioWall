"""Fake EQ-style visualizer — vertical bars that bounce.

Eight vertical bars with independent sine phases. Bar heights
pulse centered vertically so motion is symmetric about the middle.
Chunky rectangles read well even when the effective frame rate is
only 10–15 fps (SPI + PNG-mirror per-frame cost on a Pi 3 B+).
"""

from __future__ import annotations

import math

from luma.core.render import canvas

from radiowall.display import fonts

AMBER = (255, 176, 0)
AMBER_DIM = (110, 75, 0)

NUM_BARS = 8
SPEED = 0.12       # radians per frame — bigger = faster bounce
SPREAD = 0.55      # phase offset between adjacent bars


def draw(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    cy = H // 2
    max_half_h = int(H * 0.42)

    bar_slot = W / NUM_BARS
    bar_w = max(3, int(bar_slot * 0.6))
    gap = (bar_slot - bar_w) / 2

    with canvas(device) as draw_ctx:
        for i in range(NUM_BARS):
            phase = frame * SPEED + i * SPREAD
            # amplitude 0..1 via half-wave-rectified sine squared — gives
            # a "punchier" pulse than raw sine
            amp = abs(math.sin(phase)) ** 1.5
            half_h = max(2, int(max_half_h * amp))

            x = int(i * bar_slot + gap)
            y1 = cy - half_h
            y2 = cy + half_h
            draw_ctx.rectangle((x, y1, x + bar_w, y2), fill=AMBER)

            # subtle dim "ghost" trail at peak range
            draw_ctx.rectangle(
                (x, cy - max_half_h, x + bar_w, cy - max_half_h + 1),
                fill=AMBER_DIM,
            )
            draw_ctx.rectangle(
                (x, cy + max_half_h - 1, x + bar_w, cy + max_half_h),
                fill=AMBER_DIM,
            )
