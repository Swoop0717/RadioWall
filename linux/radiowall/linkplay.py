"""LinkPlay (WiiM) HTTP API client.

Base: https://{ip}/httpapi.asp?command={command} — HTTPS on 443 with a
self-signed cert (verify disabled; port 80 is refused). Ported 1:1 from
the ESP32 client:

- timeout 5 s per attempt, 2 retries with a 1 s gap (3 attempts total)
- command success == response body "OK"
- setPlayerCmd:play URLs get a PARTIAL percent-encoding: only the five
  characters : / ? & = — matching the firmware; full urllib quoting
  changes behavior on some streams, don't "fix" it
- getPlayerStatus returns JSON where `vol` may be a quoted string or a
  bare number — normalize to int

CLI:
    python -m radiowall.linkplay <ip> play <stream_url>
    python -m radiowall.linkplay <ip> stop | pause | resume
    python -m radiowall.linkplay <ip> vol <0-100>
    python -m radiowall.linkplay <ip> status
"""

from __future__ import annotations

import json
import logging
import time

import requests
import urllib3

log = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEOUT_S = 5
RETRIES = 2          # extra attempts after the first
RETRY_GAP_S = 1.0

_ENCODE_MAP = [(":", "%3A"), ("/", "%2F"), ("?", "%3F"),
               ("&", "%26"), ("=", "%3D")]


def encode_stream_url(url: str) -> str:
    """Percent-encode ONLY : / ? & = — exact ESP32 behavior. Pure."""
    for char, repl in _ENCODE_MAP:
        url = url.replace(char, repl)
    return url


class LinkPlay:
    def __init__(self, ip: str, session: requests.Session | None = None):
        self.ip = ip
        self._session = session or requests.Session()

    def _request(self, command: str, retries: int = RETRIES) -> str:
        # Command goes into the URL verbatim — do NOT pass it via params=,
        # which would percent-encode it a second time on top of our partial
        # stream-URL encoding; the WiiM decodes only once and then tries to
        # play a still-encoded (broken) URL while happily returning "OK".
        url = f"https://{self.ip}/httpapi.asp?command={command}"
        for attempt in range(retries + 1):
            if attempt:
                time.sleep(RETRY_GAP_S)
            try:
                resp = self._session.get(url, timeout=TIMEOUT_S, verify=False)
                body = resp.text.strip()
                if body:
                    return body
            except requests.RequestException as e:
                log.debug("linkplay %s attempt %d failed: %s",
                          command.split(":")[0], attempt + 1, e)
        log.warning("linkplay command failed after %d attempts: %s",
                    retries + 1, command.split(":")[0])
        return ""

    def _ok(self, command: str) -> bool:
        return self._request(command) == "OK"

    def play(self, stream_url: str) -> bool:
        return self._ok(f"setPlayerCmd:play:{encode_stream_url(stream_url)}")

    def stop(self) -> bool:
        return self._ok("setPlayerCmd:stop")

    def pause(self) -> bool:
        return self._ok("setPlayerCmd:pause")

    def resume(self) -> bool:
        return self._ok("setPlayerCmd:resume")

    def toggle_pause(self) -> bool:
        return self._ok("setPlayerCmd:onepause")

    def set_volume(self, vol: int) -> bool:
        vol = max(0, min(100, int(vol)))
        return self._ok(f"setPlayerCmd:vol:{vol}")

    def get_status(self) -> dict | None:
        """getPlayerStatus as a dict; `vol` normalized to int (or absent)."""
        body = self._request("getPlayerStatus", retries=1)
        if not body:
            return None
        try:
            status = json.loads(body)
        except ValueError:
            log.warning("getPlayerStatus: unparseable response")
            return None
        if "vol" in status:
            try:
                status["vol"] = max(0, min(100, int(str(status["vol"]).strip())))
            except ValueError:
                del status["vol"]
        return status

    def get_volume(self) -> int | None:
        status = self.get_status()
        return status.get("vol") if status else None


def _main() -> int:
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__.split("CLI:")[1])
        return 2
    wiim = LinkPlay(args[0])
    cmd = args[1]
    if cmd == "play" and len(args) == 3:
        print("OK" if wiim.play(args[2]) else "FAILED")
    elif cmd in ("stop", "pause", "resume"):
        print("OK" if getattr(wiim, cmd)() else "FAILED")
    elif cmd == "vol" and len(args) == 3:
        print("OK" if wiim.set_volume(int(args[2])) else "FAILED")
    elif cmd == "status":
        print(json.dumps(wiim.get_status(), indent=2))
    else:
        print("bad arguments")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
