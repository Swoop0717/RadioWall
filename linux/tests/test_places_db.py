"""places_db: synthetic-file parsing + nearest-search semantics."""

import struct

import pytest

from radiowall.geo import TouchCalibration, tap_to_latlon
from radiowall.places_db import HEADER, MAGIC, RECORD, PlacesDB, default_path


def _record(pid: str, lat: float, lon: float, name: str, country: str) -> bytes:
    return RECORD.pack(pid.encode(), int(lat * 100), int(lon * 100),
                       name.encode(), country.encode())


def _db_bytes(records: list[bytes], version: int = 1, magic: bytes = MAGIC) -> bytes:
    return HEADER.pack(magic, version, len(records)) + b"".join(records)


CITIES = [
    _record("vienna01", 48.21, 16.37, "Vienna", "AT"),
    _record("bratisl1", 48.15, 17.11, "Bratislava", "SK"),
    _record("tokyo001", 35.68, 139.69, "Tokyo", "JP"),
    _record("suva0001", -18.14, 178.44, "Suva", "FJ"),       # +178° lon
    _record("adak0001", 51.88, -176.63, "Adak", "US"),       # -176° lon
]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "places.bin"
    p.write_bytes(_db_bytes(CITIES))
    return PlacesDB.load(p)


def test_load_parses_all_records(db):
    assert len(db) == 5


def test_bad_magic_rejected(tmp_path):
    p = tmp_path / "bad.bin"
    p.write_bytes(_db_bytes(CITIES, magic=b"NOPE"))
    with pytest.raises(ValueError, match="magic"):
        PlacesDB.load(p)


def test_bad_version_rejected(tmp_path):
    p = tmp_path / "bad.bin"
    p.write_bytes(_db_bytes(CITIES, version=2))
    with pytest.raises(ValueError, match="version"):
        PlacesDB.load(p)


def test_nearest_simple(db):
    place = db.find_nearest(48.2, 16.4)
    assert place.name == "Vienna"
    assert place.country == "AT"


def test_nearest_prefers_closer_city(db):
    assert db.find_nearest(48.17, 17.0).name == "Bratislava"


def test_lon_wraparound_across_dateline(db):
    # A point at lon -179 is ~4.9° from Suva (+178.44) across the dateline,
    # but ~356° away without wrap handling. Adak sits 3° further north.
    place = db.find_nearest(-17.0, -179.0)
    assert place.name == "Suva"


def test_excluding_skips_and_finds_next(db):
    first = db.find_nearest(48.2, 16.4)
    second = db.find_nearest_excluding(48.2, 16.4, {first.id})
    assert second.name == "Bratislava"
    assert second.id != first.id


def test_excluding_all_returns_none(db):
    ids = {c[:16].split(b"\x00")[0].decode() for c in CITIES}
    assert db.find_nearest_excluding(0, 0, ids) is None


# --- integration against the real database (skipped if absent) ---

def test_real_places_bin():
    path = default_path()
    if not path.exists():
        pytest.skip("real places.bin not present")
    db = PlacesDB.load(path)
    assert len(db) > 10_000            # exact count varies per regeneration
    vienna = db.find_nearest(48.21, 16.37)
    assert vienna.name == "Vienna"
    assert vienna.country == "AT"      # ISO alpha-2 since the 2026-07-13 regen


# --- geo transform ---

def test_tap_center_is_null_island():
    lat, lon = tap_to_latlon(0.5, 0.5)
    assert (lat, lon) == (0.0, 0.0)


def test_tap_corners():
    assert tap_to_latlon(0.0, 0.0) == (90.0, -180.0)
    assert tap_to_latlon(1.0, 1.0) == (-90.0, 180.0)


def test_tap_vienna_ish():
    # Vienna: lon 16.37 → u = (16.37+180)/360 ≈ 0.5455; lat 48.21 → v ≈ 0.2322
    lat, lon = tap_to_latlon(0.5455, 0.2322)
    assert abs(lat - 48.2) < 0.2
    assert abs(lon - 16.4) < 0.2


def test_tap_with_calibration_subrect():
    # Map occupies the middle half of the frame in both axes.
    cal = TouchCalibration(x0=0.25, y0=0.25, x1=0.75, y1=0.75)
    assert tap_to_latlon(0.5, 0.5, cal) == (0.0, 0.0)
    assert tap_to_latlon(0.25, 0.25, cal) == (90.0, -180.0)
    # Taps outside the map area clamp to the map edge.
    assert tap_to_latlon(0.0, 0.0, cal) == (90.0, -180.0)
