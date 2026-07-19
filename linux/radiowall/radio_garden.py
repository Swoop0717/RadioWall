"""Radio.garden API client (unofficial, no auth).

Endpoints (ported 1:1 from the ESP32 firmware, the working reference):

    GET /api/ara/content/page/{place_id}/channels
        → JSON: data.content[].items[].page.{title, url}
          station id = the URL segment after "/listen/{slug}/"
    GET /api/ara/content/listen/{station_id}/channel.mp3
        → 302 redirect; the Location header is the actual stream URL

Timeouts 10 s, User-Agent "RadioWall/1.0", max 100 stations per place —
all matching the ESP32 constants. No retries at this layer (the caller
surfaces failures as transient status text; NEXT simply moves on).

CLI:
    python -m radiowall.radio_garden stations <place_id>
    python -m radiowall.radio_garden resolve <station_id>
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

BASE = "https://radio.garden/api/ara/content"
TIMEOUT_S = 10
USER_AGENT = "RadioWall/1.0"
MAX_STATIONS = 100


@dataclass(frozen=True)
class Station:
    id: str
    title: str


def parse_channels(payload: dict) -> list[Station]:
    """Extract stations from a /channels response. Pure — unit-testable."""
    stations: list[Station] = []
    try:
        sections = payload["data"]["content"]
    except (KeyError, TypeError):
        return stations
    if not isinstance(sections, list):
        return stations
    for section in sections:
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            page = item.get("page") or {}
            title = page.get("title")
            url = page.get("url")
            if not title or not url:
                continue
            # url shape: /listen/{slug}/{station_id}
            marker = "/listen/"
            idx = url.find(marker)
            if idx < 0:
                continue
            rest = url[idx + len(marker):]
            slash = rest.find("/")
            if slash < 0:
                continue
            station_id = rest[slash + 1:]
            if not station_id:
                continue
            stations.append(Station(id=station_id, title=title))
            if len(stations) >= MAX_STATIONS:
                return stations
    return stations


class RadioGarden:
    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def get_stations(self, place_id: str) -> list[Station]:
        url = f"{BASE}/page/{place_id}/channels"
        try:
            resp = self._session.get(url, timeout=TIMEOUT_S)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("get_stations(%s) failed: %s", place_id, e)
            return []
        stations = parse_channels(payload)
        log.info("place %s: %d stations", place_id, len(stations))
        return stations

    def resolve_stream_url(self, station_id: str) -> str | None:
        url = f"{BASE}/listen/{station_id}/channel.mp3"
        try:
            resp = self._session.get(url, timeout=TIMEOUT_S,
                                     allow_redirects=False)
        except requests.RequestException as e:
            log.warning("resolve_stream_url(%s) failed: %s", station_id, e)
            return None
        location = resp.headers.get("Location")
        if not location:
            log.warning("resolve_stream_url(%s): no redirect (HTTP %d)",
                        station_id, resp.status_code)
            return None
        return location


def _main() -> int:
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 3 or sys.argv[1] not in ("stations", "resolve"):
        print("usage: python -m radiowall.radio_garden stations <place_id>\n"
              "       python -m radiowall.radio_garden resolve <station_id>")
        return 2
    rg = RadioGarden()
    if sys.argv[1] == "stations":
        for i, st in enumerate(rg.get_stations(sys.argv[2]), 1):
            print(f"{i:3d}. {st.title}   [{st.id}]")
    else:
        print(rg.resolve_stream_url(sys.argv[2]) or "resolve failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
