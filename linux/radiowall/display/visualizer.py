"""Simple "music visualizer" demo screen for button presses.

Four concentric circles that breathe out of phase, with a centered
caption. Lives in display/ alongside the other draw functions so
the main loop can swap it in for the VFD mockup.
"""

from __future__ import annotations

import math

from luma.core.render import canvas

from radiowall.display import fonts

AMBER = (255, 176, 0)
AMBER_DIM = (110, 75, 0)


def draw(device, frame: int, fs: fonts.FontSet) -> None:
    W, H = device.width, device.height
    cx, cy = W // 2, H // 2
    r_base = min(W, H) // 3

    with canvas(device) as draw_ctx:
        for i in range(4):
            phase = (frame * 0.08 + i * 0.8) % (2 * math.pi)
            radius = int(r_base + 16 * math.sin(phase) + i * 6)
            if radius > 1:
                color = AMBER if i == 0 else AMBER_DIM
                draw_ctx.ellipse(
                    (cx - radius, cy - radius, cx + radius, cy + radius),
                    outline=color,
                    width=2,
                )

        label = "VISUALIZER"
        tw = draw_ctx.textlength(label, font=fs.small)
        draw_ctx.text(
            (cx - tw // 2, cy - fs.small.size // 2),
            label,
            font=fs.small,
            fill=AMBER,
        )
