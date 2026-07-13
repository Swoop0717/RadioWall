"""State-driven screens for the 256×64 OLED (and the ST7789 dev rig).

One entry point: `draw_status_screen(device, frame, fs, snap)` — renders
whatever the `Snapshot` says (idle / loading / playing, transient status,
volume overlay). Geometry follows the proven draw_mockup layout:
separators at 26 % / 74 % of height, big scrolling band in the middle.

Demo (no hardware):
    RADIOWALL_EMULATE=1 RADIOWALL_EMULATE_W=256 RADIOWALL_EMULATE_H=64 \
        python -m radiowall.display.screens
"""

from __future__ import annotations

from luma.core.render import canvas

from radiowall.display import fonts
from radiowall.state import Phase, Snapshot

AMBER = (255, 176, 0)
AMBER_DIM = (110, 75, 0)

SCROLL_PX_PER_FRAME = 2
SCROLL_GAP = "   ·   "


def scroll_text(draw, text: str, font, y: int, width: int, frame: int,
                fill=AMBER) -> None:
    """Horizontally scroll `text` if wider than `width`, else center it."""
    text_w = int(draw.textlength(text, font=font))
    if text_w <= width:
        draw.text(((width - text_w) // 2, y), text, font=font, fill=fill)
        return
    looped = text + SCROLL_GAP
    loop_w = int(draw.textlength(looped, font=font))
    offset = (frame * SCROLL_PX_PER_FRAME) % loop_w
    draw.text((-offset, y), looped, font=font, fill=fill)
    draw.text((-offset + loop_w, y), looped, font=font, fill=fill)


def _band_geometry(device, fs: fonts.FontSet):
    H = device.height
    top_sep = int(H * 0.26)
    bot_sep = int(H * 0.74)
    band_y = top_sep + 2 + max(0, (bot_sep - top_sep - fs.big.size) // 2)
    return top_sep, bot_sep, band_y


def draw_status_screen(device, frame: int, fs: fonts.FontSet,
                       snap: Snapshot) -> None:
    W, H = device.width, device.height
    pad = max(2, W // 64)
    top_sep, bot_sep, band_y = _band_geometry(device, fs)

    with canvas(device) as draw:
        if snap.phase is Phase.IDLE and not snap.status_text:
            _idle(draw, W, H, fs, frame)
        else:
            _header(draw, snap, fs, pad)
            draw.line((0, top_sep, W, top_sep), fill=AMBER_DIM)
            draw.line((0, bot_sep, W, bot_sep), fill=AMBER_DIM)
            _band(draw, snap, fs, band_y, W, frame)

        if snap.volume_flash:
            _volume_overlay(draw, snap, fs, W, H, bot_sep)
        elif snap.phase is not Phase.IDLE or snap.status_text:
            _footer(draw, snap, fs, pad, bot_sep, W)


def _header(draw, snap: Snapshot, fs, pad: int) -> None:
    W = draw.im.size[0]
    right_w = 0
    if snap.station_total:
        right = f"{snap.station_index}/{snap.station_total}"
        right_w = draw.textlength(right, font=fs.small)
        draw.text((W - right_w - pad, pad), right, font=fs.small, fill=AMBER)

    left = snap.place_name or ""
    if snap.country:
        left = f"{left} · {snap.country}"
    font = fs.pick_small(left)
    avail = W - right_w - 3 * pad
    while left and draw.textlength(left, font=font) > avail:
        left = left[:-2].rstrip() + "…"    # long country names must not
    draw.text((pad, pad), left, font=font, fill=AMBER)   # hit the counter


def _band(draw, snap: Snapshot, fs, band_y: int, W: int, frame: int) -> None:
    if snap.status_text:
        scroll_text(draw, snap.status_text, fs.big, band_y, W, frame)
    elif snap.phase is Phase.LOADING:
        dots = "." * (1 + (frame // 12) % 3)
        scroll_text(draw, f"Tuning{dots}", fs.big, band_y, W, frame=0)
    else:
        title = snap.station_title
        scroll_text(draw, title, fs.pick_big(title), band_y, W, frame)


def _footer(draw, snap: Snapshot, fs, pad: int, bot_sep: int, W: int) -> None:
    # Just the volume — no state word. If music plays you hear it, if it's
    # tuning the band says so, and idle has its own screen.
    y = bot_sep + 2   # tight: small font + descenders must fit in H-bot_sep
    draw.text((pad, y), f"vol {snap.volume}", font=fs.small, fill=AMBER)


def _idle(draw, W: int, H: int, fs, frame: int) -> None:
    title = "RADIOWALL"
    hint = "touch the map"
    tw = draw.textlength(title, font=fs.big)
    hw = draw.textlength(hint, font=fs.small)
    draw.text(((W - tw) // 2, int(H * 0.18)), title, font=fs.big, fill=AMBER)
    # gentle blink so the panel doesn't look frozen
    if (frame // 40) % 2 == 0:
        draw.text(((W - hw) // 2, int(H * 0.68)), hint,
                  font=fs.small, fill=AMBER_DIM)


def _volume_overlay(draw, snap: Snapshot, fs, W: int, H: int,
                    bot_sep: int) -> None:
    """Replace the footer strip with a volume bar while the flash lasts."""
    pad = max(2, W // 64)
    y0 = bot_sep + 1
    draw.rectangle((0, y0, W, H), fill=(0, 0, 0))
    label = f"vol {snap.volume}"
    lw = draw.textlength(label, font=fs.small)
    draw.text((pad, y0 + pad), label, font=fs.small, fill=AMBER)
    bar_x0 = int(lw) + pad * 3
    bar_x1 = W - pad
    bar_y0 = y0 + pad + 2
    bar_y1 = H - pad
    draw.rectangle((bar_x0, bar_y0, bar_x1, bar_y1), outline=AMBER_DIM)
    fill_w = int((bar_x1 - bar_x0 - 2) * snap.volume / 100)
    if fill_w > 0:
        draw.rectangle((bar_x0 + 1, bar_y0 + 1,
                        bar_x0 + 1 + fill_w, bar_y1 - 1), fill=AMBER)


def _demo() -> None:
    """Cycle fake snapshots in the emulator (or on the real panel)."""
    import itertools
    import time

    from radiowall.display.factory import make_device

    device = make_device()
    fs = fonts.fonts_for(device.height)
    snaps = [
        ("idle", Snapshot()),
        ("loading", Snapshot(phase=Phase.LOADING, place_name="Vienna")),
        ("playing short", Snapshot(phase=Phase.PLAYING, place_name="Vienna",
                                   station_title="Radio Wien",
                                   station_index=3, station_total=12,
                                   volume=45)),
        ("playing long", Snapshot(phase=Phase.PLAYING, place_name="Reykjavik",
                                  station_title="Rás 2 — Icelandic public "
                                                "radio with a very long name",
                                  station_index=1, station_total=4,
                                  volume=45)),
        ("volume flash", Snapshot(phase=Phase.PLAYING, place_name="Vienna",
                                  station_title="Radio Wien",
                                  station_index=3, station_total=12,
                                  volume=72, volume_flash=True)),
        ("error", Snapshot(phase=Phase.IDLE, status_text="No stations found",
                           volume=45)),
    ]
    print("cycling demo snapshots; Ctrl+C to stop")
    frame = 0
    try:
        for name, snap in itertools.cycle(snaps):
            print(" ", name)
            for _ in range(150):          # ~3 s per snapshot at 50 fps
                draw_status_screen(device, frame, fs, snap)
                frame += 1
                time.sleep(0.02)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _demo()
