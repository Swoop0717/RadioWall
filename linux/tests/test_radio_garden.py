"""radio_garden: pure parsing against a captured real response."""

import json
from pathlib import Path

from radiowall.radio_garden import MAX_STATIONS, parse_channels

FIXTURE = Path(__file__).parent / "fixtures" / "channels_vienna.json"


def _payload(items: list[dict]) -> dict:
    return {"data": {"content": [{"items": items}]}}


def test_real_fixture_parses():
    payload = json.loads(FIXTURE.read_text())
    stations = parse_channels(payload)
    assert len(stations) == MAX_STATIONS  # Vienna has >100; truncated
    assert stations[0].title == "88.6 Classic Rock"
    assert stations[0].id == "b7ew6wyx"
    assert all(st.id and st.title for st in stations)


def test_station_id_is_segment_after_slug():
    payload = _payload([
        {"page": {"title": "Radio X", "url": "/listen/radio-x/AbC123"}},
    ])
    (st,) = parse_channels(payload)
    assert st.id == "AbC123"
    assert st.title == "Radio X"


def test_items_without_page_title_or_url_skipped():
    payload = _payload([
        {"page": {"title": "No URL"}},
        {"page": {"url": "/listen/x/y1"}},
        {"notpage": {}},
        {"page": {"title": "OK", "url": "/listen/ok/id9"}},
        {"page": {"title": "Weird", "url": "/browse/whatever"}},
        {"page": {"title": "No id", "url": "/listen/slug-only"}},
    ])
    (st,) = parse_channels(payload)
    assert st.id == "id9"


def test_truncates_at_max_stations():
    items = [{"page": {"title": f"S{i}", "url": f"/listen/s/{i}"}}
             for i in range(150)]
    assert len(parse_channels(_payload(items))) == MAX_STATIONS


def test_malformed_payloads_return_empty():
    assert parse_channels({}) == []
    assert parse_channels({"data": {}}) == []
    assert parse_channels({"data": {"content": None}}) == []
    assert parse_channels(None) == []
