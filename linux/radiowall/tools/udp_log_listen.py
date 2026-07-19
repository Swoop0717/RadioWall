"""Listen for UDP log lines broadcast by the Pi and print them with colour.

Run this on your dev laptop:

    python -m radiowall.tools.udp_log_listen

Then on the Pi, point logging at your laptop (whatever its LAN IP is):

    RADIOWALL_LOG_UDP=192.168.0.10:9999 python -m radiowall

Default bind is 0.0.0.0:9999 so any machine on the LAN can send to it.
Colour is applied by matching the level word in the formatted line, so
this also works for any other UTF-8 log stream hitting the port.
"""

from __future__ import annotations

import argparse
import socket
import sys

_COLORS = {
    "DEBUG": "\033[2m",        # dim
    "INFO ": "",                # default
    "WARNI": "\033[33m",        # yellow (LEVELNAME is formatted %-5s)
    "ERROR": "\033[31m",        # red
    "CRITI": "\033[1;31m",      # bold red
}
_RESET = "\033[0m"


def _colour_for(line: str) -> str:
    # format is "HH:MM:SS LEVEL-5s name: msg" — find the level token
    parts = line.split(" ", 2)
    if len(parts) >= 2:
        return _COLORS.get(parts[1][:5], "")
    return ""


def main() -> int:
    p = argparse.ArgumentParser(description="RadioWall UDP log listener")
    p.add_argument("--host", default="0.0.0.0",
                   help="interface to bind (default: all)")
    p.add_argument("--port", type=int, default=9999)
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"listening on {args.host}:{args.port} — Ctrl+C to stop",
          file=sys.stderr)

    try:
        while True:
            data, _addr = sock.recvfrom(65535)
            line = data.decode("utf-8", errors="replace").rstrip()
            c = _colour_for(line)
            print(f"{c}{line}{_RESET}" if c else line, flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
