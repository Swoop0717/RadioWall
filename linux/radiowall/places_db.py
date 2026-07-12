"""Radio.garden places database — reader + nearest-city search.

Reads the packed binary produced by tools/compile_places.py (the same
file the ESP32 loads from LittleFS):

    Header (16 B): magic "RGPL", uint16 version (=1), uint32 count, 6 B pad
    Record (52 B): char[16] id, int16 lat*100, int16 lon*100,
                   char[28] name, char[4] country      (little-endian)

Nearest-city search replicates the ESP32 exactly: linear scan minimizing
squared Euclidean distance in the *100-scaled integer lat/lon plane, with
longitude wraparound at ±180° (±18000 in scaled units). No haversine, no
latitude correction — a deliberate approximation that's fine at city
granularity and keeps behavior identical across both tracks.

CLI: python -m radiowall.places_db 48.21 16.37   → nearest place
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"RGPL"
VERSION = 1
HEADER = struct.Struct("<4sHI6x")
RECORD = struct.Struct("<16shh28s4s")

_LON_WRAP = 18000  # 180° in lat/lon*100 units
_LON_FULL = 36000


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Place:
    id: str
    lat100: int
    lon100: int
    name: str
    country: str

    @property
    def lat(self) -> float:
        return self.lat100 / 100.0

    @property
    def lon(self) -> float:
        return self.lon100 / 100.0


class PlacesDB:
    def __init__(self, places: list[Place]):
        self._places = places

    def __len__(self) -> int:
        return len(self._places)

    @classmethod
    def load(cls, path: Path | str) -> "PlacesDB":
        data = Path(path).read_bytes()
        magic, version, count = HEADER.unpack_from(data, 0)
        if magic != MAGIC:
            raise ValueError(f"{path}: bad magic {magic!r}")
        if version != VERSION:
            raise ValueError(f"{path}: unsupported version {version}")
        places = []
        offset = HEADER.size
        for _ in range(count):
            pid, lat100, lon100, name, country = RECORD.unpack_from(data, offset)
            offset += RECORD.size
            places.append(Place(
                id=_cstr(pid), lat100=lat100, lon100=lon100,
                name=_cstr(name), country=_cstr(country)))
        return cls(places)

    def find_nearest(self, lat: float, lon: float) -> Place | None:
        return self.find_nearest_excluding(lat, lon, frozenset())

    def find_nearest_excluding(self, lat: float, lon: float,
                               exclude: frozenset[str] | set[str]) -> Place | None:
        target_lat = int(lat * 100)
        target_lon = int(lon * 100)
        best: Place | None = None
        best_d = None
        for p in self._places:
            if p.id in exclude:
                continue
            dlat = p.lat100 - target_lat
            dlon = p.lon100 - target_lon
            if dlon > _LON_WRAP:
                dlon -= _LON_FULL
            elif dlon < -_LON_WRAP:
                dlon += _LON_FULL
            d = dlat * dlat + dlon * dlon
            if best_d is None or d < best_d:
                best_d = d
                best = p
        return best


def default_path() -> Path:
    """RADIOWALL_PLACES env → linux/data/places.bin → repo esp32/data/places.bin."""
    env = os.getenv("RADIOWALL_PLACES", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    local = here.parents[1] / "data" / "places.bin"       # linux/data/
    if local.exists():
        return local
    return here.parents[2] / "esp32" / "data" / "places.bin"


def _main() -> int:
    import sys

    if len(sys.argv) != 3:
        print("usage: python -m radiowall.places_db <lat> <lon>")
        return 2
    lat, lon = float(sys.argv[1]), float(sys.argv[2])
    db = PlacesDB.load(default_path())
    print(f"{len(db)} places loaded from {default_path()}")
    place = db.find_nearest(lat, lon)
    if place is None:
        print("no places")
        return 1
    print(f"nearest to ({lat}, {lon}): {place.name}, {place.country} "
          f"({place.lat}, {place.lon})  id={place.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
