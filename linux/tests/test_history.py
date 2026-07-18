"""History store: dedup, favorite pinning, cap, persistence — plus the
worker's record-after-threshold and replay-from-entry behavior."""

import time

import pytest

from radiowall import config, history
from radiowall.history import Entry


@pytest.fixture
def hist(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOWALL_CONFIG", str(tmp_path / "config.json"))
    config.reset_cache_for_tests()
    history.reset_cache_for_tests()
    yield history
    history.reset_cache_for_tests()
    config.reset_cache_for_tests()


def _entry(i, fav=False):
    return Entry(station_id=f"s{i}", station_title=f"Station {i}",
                 place_id=f"p{i}", place_name=f"City {i}", country="AT",
                 lat=48.0, lon=16.0, favorite=fav)


def test_add_newest_first_and_persisted(hist):
    hist.add(_entry(1))
    hist.add(_entry(2))
    assert [e.station_id for e in hist.entries()] == ["s2", "s1"]
    history.reset_cache_for_tests()        # force re-read from disk
    assert [e.station_id for e in hist.entries()] == ["s2", "s1"]


def test_replay_dedups_and_keeps_star(hist):
    hist.add(_entry(1))
    hist.toggle_favorite("s1")
    hist.add(_entry(2))
    hist.add(_entry(1))                    # replayed later
    ids = [e.station_id for e in hist.entries()]
    assert ids == ["s1", "s2"]             # moved to top, no duplicate
    assert hist.entries()[0].favorite      # star survived the replay


def test_cap_evicts_oldest_nonfavorites_only(hist):
    hist.add(_entry(0, fav=False))
    hist.toggle_favorite("s0")             # star the oldest
    for i in range(1, history.MAX_ENTRIES + 5):
        hist.add(_entry(i))
    all_ids = {e.station_id for e in hist.entries()}
    assert "s0" in all_ids                 # favorite outlived the cap
    plain = [e for e in hist.entries() if not e.favorite]
    assert len(plain) == history.MAX_ENTRIES


def test_favorites_filter_and_unstar(hist):
    hist.add(_entry(1))
    hist.add(_entry(2))
    hist.toggle_favorite("s1")
    assert [e.station_id for e in hist.entries(favorites_only=True)] == ["s1"]
    assert hist.toggle_favorite("s1") is False
    assert hist.entries(favorites_only=True) == []


# --- worker integration -------------------------------------------------------

def test_worker_records_after_threshold_and_replays(hist):
    from tests.test_state import FakeRG, FakeWiim, FakePlaces, _stations
    from radiowall.radio import RadioWorker, PlayAt
    from radiowall.state import AppState, Phase

    rg = FakeRG({"p1": _stations(2)})
    wiim = FakeWiim()
    state = AppState()
    w = RadioWorker(state, FakePlaces(), rg=rg, wiim=wiim, use_decoder=False)
    w._record_after_s = 0.05               # don't wait 30 s in a test
    w.start()
    try:
        w.submit(PlayAt(0.0, 0.0))
        deadline = time.time() + 2.0
        while not hist.entries() and time.time() < deadline:
            time.sleep(0.02)
        entries = hist.entries()
        assert len(entries) == 1
        e = entries[0]
        assert e.station_id == "S0"
        assert e.place_name and e.country

        # replay it: same station plays again, session supports NEXT
        w.play_history(e)
        time.sleep(0.3)
        assert wiim.played[-1].endswith("S0")
        assert state.snapshot().phase == Phase.PLAYING
        assert state.snapshot().station_title == "S 0"
    finally:
        w.stop()


def test_worker_skipped_station_not_recorded(hist):
    from tests.test_state import FakeRG, FakeWiim, FakePlaces, _stations
    from radiowall.radio import RadioWorker, PlayAt, Next
    from radiowall.state import AppState

    rg = FakeRG({"p1": _stations(2)})
    state = AppState()
    w = RadioWorker(state, FakePlaces(), rg=rg, wiim=FakeWiim(),
                    use_decoder=False)
    w._record_after_s = 0.5
    w.start()
    try:
        w.submit(PlayAt(0.0, 0.0))         # S0 starts...
        time.sleep(0.15)
        w.submit(Next())                   # ...skipped before threshold
        deadline = time.time() + 1.5
        while not hist.entries() and time.time() < deadline:
            time.sleep(0.02)
        ids = [e.station_id for e in hist.entries()]
        assert ids == ["S1"]               # only the survivor recorded
    finally:
        w.stop()


def test_worker_favorite_current_records_and_stars(hist):
    from tests.test_state import FakeRG, FakeWiim, FakePlaces, _stations
    from radiowall.radio import RadioWorker, PlayAt
    from radiowall.state import AppState

    rg = FakeRG({"p1": _stations(1)})
    state = AppState()
    w = RadioWorker(state, FakePlaces(), rg=rg, wiim=FakeWiim(),
                    use_decoder=False)
    w.start()                              # default 30 s window: NOT recorded
    try:
        w.submit(PlayAt(0.0, 0.0))
        time.sleep(0.3)
        assert hist.entries() == []        # threshold far away
        w.favorite_current()               # triple-press
        time.sleep(0.3)
        entries = hist.entries(favorites_only=True)
        assert len(entries) == 1 and entries[0].station_id == "S0"
        assert "★" in state.snapshot().status_text

        w.favorite_current()               # toggle off
        time.sleep(0.3)
        assert hist.entries(favorites_only=True) == []
        assert len(hist.entries()) == 1    # stays in plain history
    finally:
        w.stop()


def test_worker_favorite_with_nothing_playing(hist):
    from tests.test_state import FakeRG, FakeWiim, FakePlaces
    from radiowall.radio import RadioWorker
    from radiowall.state import AppState

    state = AppState()
    w = RadioWorker(state, FakePlaces(), rg=FakeRG({}), wiim=FakeWiim(),
                    use_decoder=False)
    w.start()
    try:
        w.favorite_current()
        time.sleep(0.3)
        assert state.snapshot().status_text == "Nothing playing"
        assert hist.entries() == []
    finally:
        w.stop()
