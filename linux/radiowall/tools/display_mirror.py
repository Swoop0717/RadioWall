"""Watch the Pi's live display frame on your laptop via UDP broadcast.

Run on any machine on the same LAN as the Pi:

    python radiowall/tools/display_mirror.py           # from linux/
    python -m radiowall.tools.display_mirror            # if installed

And on the Pi:

    RADIOWALL_MIRROR=1 python -m radiowall

The Pi broadcasts PNG-encoded frames to 255.255.255.255:9000. This
tool binds 0.0.0.0:9000, decodes each frame, and shows it in a
pygame window upscaled. Zero config on either end.

If you're running this under WSL and nothing shows up: WSL2's NAT
drops LAN broadcasts. Run under native Python on Windows instead,
or enable WSL2 mirrored networking.
"""

from __future__ import annotations

import argparse
import io
import socket
import sys

import pygame
from PIL import Image


def main() -> int:
    p = argparse.ArgumentParser(description="RadioWall display mirror")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--scale", type=int, default=4,
                   help="integer upscale factor (default 4 -> 960x540)")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.05)
    print(f"listening on 0.0.0.0:{args.port} — Ctrl+C to stop",
          file=sys.stderr)

    pygame.init()
    screen = None
    clock = pygame.time.Clock()
    caption = f"RadioWall mirror :{args.port}"
    pygame.display.set_caption(caption)

    running = True
    frames = 0
    try:
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False

            try:
                data, _ = sock.recvfrom(65536)
            except socket.timeout:
                clock.tick(60)
                continue

            try:
                img = Image.open(io.BytesIO(data)).convert("RGB")
            except Exception as e:
                print(f"bad frame: {e}", file=sys.stderr)
                continue

            w, h = img.size
            out = (w * args.scale, h * args.scale)
            if screen is None or screen.get_size() != out:
                screen = pygame.display.set_mode(out)
                pygame.display.set_caption(f"{caption}  {w}x{h} x{args.scale}")

            # nearest-neighbor upscale to keep pixel edges crisp
            surf = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
            surf = pygame.transform.scale(surf, out)
            screen.blit(surf, (0, 0))
            pygame.display.flip()
            frames += 1
            clock.tick(60)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        pygame.quit()
        print(f"exit after {frames} frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
