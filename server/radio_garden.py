"""Radio.garden API client.

Fetches places, finds nearest stations to coordinates, and resolves stream URLs.
"""

import logging
import random
import time
from datetime import datetime

import geopy.distance
import requests

logger = logging.getLogger(__name__)

# Radio.garden API returns geo as [longitude, latitude]
GEO_LON_IDX = 0
GEO_LAT_IDX = 1


class RadioGardenClient:
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "http://radio.garden/api/ara/content")
        self.cache_ttl = config.get("cache_places_seconds", 3600)
        self.n_stations = config.get("n_stations", 20)
        self.selection_mode = config.get("selection_mode", "random")

        self._places: list[dict] = []
        self._places_fetched_at: float = 0
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Places cache
    # ------------------------------------------------------------------

    def _refresh_places_if_needed(self):
        if self._places and (time.time() - self._places_fetched_at) < self.cache_ttl:
            return
        logger.info("Fetching places from Radio.garden ...")
        resp = self._session.get(f"{self.base_url}/places")
        resp.raise_for_status()
        self._places = resp.json()["data"]["list"]
        self._places_fetched_at = time.time()
        logger.info("Loaded %d places", len(self._places))

    # ------------------------------------------------------------------
    # Find nearest stations
    # ------------------------------------------------------------------

    def find_nearest_stations(self, lat: float, lon: float) -> dict:
        """Return a randomly selected station near (lat, lon).

        Returns dict with keys: station_name, location, country, stream_url
        Raises RuntimeError if no station can be found.
        """
        self._refresh_places_if_needed()

        # Calculate distances
        target = (lat, lon)
        places_with_dist = []
        for place in self._places:
            place_lat = place["geo"][GEO_LAT_IDX]
            place_lon = place["geo"][GEO_LON_IDX]
            dist = geopy.distance.geodesic((place_lat, place_lon), target).km
            places_with_dist.append({**place, "_dist": dist})

        places_with_dist.sort(key=lambda p: p["_dist"])

        # Collect places until we have enough stations
        selected_places = []
        total_size = 0
        for place in places_with_dist:
            if total_size >= self.n_stations:
                break
            selected_places.append(place)
            total_size += place.get("size", 1)

        if not selected_places:
            raise RuntimeError(f"No radio places found near ({lat}, {lon})")

        # Fetch channels from selected places
        channels = []
        for place in selected_places:
            try:
                resp = self._session.get(
                    f"{self.base_url}/page/{place['id']}/channels"
                )
                resp.raise_for_status()
                data = resp.json()
                items = data["data"]["content"][0]["items"]

                remaining = self.n_stations - len(channels)
                if place is selected_places[-1] and len(items) > remaining:
                    channels.extend(random.sample(items, remaining))
                else:
                    channels.extend(items)
            except Exception:
                logger.warning("Failed to fetch channels for %s", place.get("title"))
                continue

        if not channels:
            raise RuntimeError(f"No channels found near ({lat}, {lon})")

        # Pick a station
        if self.selection_mode == "nearest":
            channel = channels[0]
        elif self.selection_mode == "popular":
            # channels are already somewhat ordered by popularity within a place
            channel = channels[0]
        else:
            random.seed(str(datetime.now()))
            channel = random.choice(channels)

        # Resolve stream URL
        # Channel structure: {"page": {"url": "/listen/station-name/ID", "title": "...", ...}}
        page = channel["page"]
        station_id = page["url"].split("/")[-1]
        station_name = page["title"]
        place_info = selected_places[0]

        stream_url = self.get_stream_url(station_id)

        return {
            "station_name": station_name,
            "station_id": station_id,
            "location": place_info.get("title", "Unknown"),
            "country": place_info.get("country", "Unknown"),
            "stream_url": stream_url,
        }

    # ------------------------------------------------------------------
    # Stream URL
    # ------------------------------------------------------------------

    def get_stream_url(self, station_id: str) -> str:
        """Resolve a station ID to its actual stream URL.

        Radio.garden redirects /listen/{id}/channel.mp3 to the real stream.
        Some streams have broken SSL certs, so we fall back to the redirect
        Location header or the Radio.garden URL itself (the UPnP speaker
        will follow the redirect on its own).
        """
        url = f"{self.base_url}/listen/{station_id}/channel.mp3"
        try:
            # Only follow the first redirect to get the real stream URL,
            # don't follow all the way (avoids SSL issues with stream servers)
            resp = self._session.head(url, allow_redirects=False, timeout=10)
            if resp.status_code in (301, 302, 307, 308):
                return resp.headers.get("Location", url)
            return resp.url
        except Exception:
            logger.warning("Could not resolve stream URL for %s, using direct URL", station_id)
            return url
