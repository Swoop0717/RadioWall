"""Find WiiM / LinkPlay speakers on the LAN via SSDP.

LinkPlay firmware answers UPnP M-SEARCH; the LOCATION header points at
a device-description XML whose manufacturer/model identifies it. That
gives us name + IP with zero configuration — the setup UI just shows
the list and the user confirms.

`discover()` blocks a few seconds — call it from a worker thread.
"""

from __future__ import annotations

import logging
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

SSDP_ADDR = ("239.255.255.250", 1900)
MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: upnp:rootdevice\r\n"
    "\r\n"
).encode()

# Substrings (lowercased) in the description XML that mark a LinkPlay
# device. WiiM, Arylic, Audio Pro etc. all ship LinkPlay firmware.
_LINKPLAY_MARKERS = ("linkplay", "wiim")


@dataclass(frozen=True)
class Speaker:
    name: str
    ip: str


def _xml_tag(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>([^<]*)</{tag}>", xml, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _probe_location(url: str) -> Speaker | None:
    ip = urlparse(url).hostname or ""
    if not ip:
        return None
    try:
        xml = requests.get(url, timeout=2).text
    except requests.RequestException:
        return None
    haystack = xml.lower()
    if not any(marker in haystack for marker in _LINKPLAY_MARKERS):
        return None
    name = _xml_tag(xml, "friendlyName") or _xml_tag(xml, "modelName") or ip
    return Speaker(name=name, ip=ip)


def discover(timeout_s: float = 3.0) -> list[Speaker]:
    """M-SEARCH the LAN and return LinkPlay speakers, deduped by IP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for _ in range(2):                    # UDP: send twice, it's lossy
            sock.sendto(MSEARCH, SSDP_ADDR)

        locations: list[str] = []
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            m = re.search(rb"(?im)^LOCATION:\s*(\S+)", data)
            if m:
                loc = m.group(1).decode("ascii", errors="replace")
                if loc not in locations:
                    locations.append(loc)
    finally:
        sock.close()

    speakers: dict[str, Speaker] = {}
    for loc in locations:
        sp = _probe_location(loc)
        if sp is not None and sp.ip not in speakers:
            speakers[sp.ip] = sp
    found = list(speakers.values())
    log.info("ssdp: %d responses, %d LinkPlay speakers: %s",
             len(locations), len(found),
             ", ".join(f"{s.name}@{s.ip}" for s in found) or "-")
    return found


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for s in discover():
        print(f"{s.name}  {s.ip}")
