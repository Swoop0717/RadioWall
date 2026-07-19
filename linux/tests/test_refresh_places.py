"""places.bin refresher: format round-trip, the refuse-to-shrink and
refuse-truncated gates, and the atomic swap with backup."""

import json

import pytest

from radiowall.places_db import PlacesDB
from radiowall.tools import refresh_places as rp


def _fake_place(i, country="Austria", lat=48.0, lon=16.0):
    return {"id": f"place{i:05d}", "title": f"City {i}",
            "country": country, "geo": [lon, lat]}


def _write_bin(path, places):
    mapping = dict(rp.COUNTRY_OVERRIDES)
    mapping.setdefault("Austria", "AT")
    path.write_bytes(rp.encode(places, mapping))


@pytest.fixture
def bin_path(tmp_path):
    p = tmp_path / "places.bin"
    _write_bin(p, [_fake_place(i) for i in range(9000)])
    (tmp_path / "countries.json").write_text(json.dumps({"AT": "Austria"}))
    return p


def test_encode_roundtrip(tmp_path):
    p = tmp_path / "places.bin"
    _write_bin(p, [_fake_place(1, lat=48.21, lon=16.37),
                   _fake_place(2, lat=-3.55, lon=143.63)])
    db = PlacesDB.load(p)
    assert len(db) == 2
    place = db.find_nearest(48.2, 16.4)
    assert place.name == "City 1"
    assert place.country == "AT"


def test_refresh_installs_and_backs_up(bin_path):
    new = [_fake_place(i) for i in range(100, 9600)]
    added, removed = rp.refresh(bin_path, new)
    assert (added, removed) == (600, 100)
    assert len(PlacesDB.load(bin_path)) == 9500
    backup = bin_path.with_suffix(".bin.bak")
    assert len(PlacesDB.load(backup)) == 9000


def test_refresh_refuses_small_list(bin_path):
    with pytest.raises(RuntimeError, match="refusing"):
        rp.refresh(bin_path, [_fake_place(i) for i in range(100)])
    assert len(PlacesDB.load(bin_path)) == 9000     # untouched


def test_refresh_refuses_shrunk_list(bin_path):
    with pytest.raises(RuntimeError, match="shrank"):
        rp.refresh(bin_path, [_fake_place(i) for i in range(8050)])
    assert len(PlacesDB.load(bin_path)) == 9000


def test_refresh_dry_run_writes_nothing(bin_path):
    before = bin_path.read_bytes()
    added, removed = rp.refresh(
        bin_path, [_fake_place(i) for i in range(9100)], dry_run=True)
    assert added == 100 and removed == 0
    assert bin_path.read_bytes() == before
    assert not bin_path.with_suffix(".bin.bak").exists()
    assert not bin_path.with_suffix(".bin.tmp").exists()


def test_unknown_country_becomes_unknown_code(tmp_path):
    p = tmp_path / "places.bin"
    _write_bin(p, [_fake_place(1, country="Atlantis")])
    db = PlacesDB.load(p)
    assert db.find_nearest(48, 16).country == "??"
