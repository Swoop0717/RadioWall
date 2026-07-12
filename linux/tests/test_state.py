"""state.Session city-hop semantics + AppState snapshot behavior +
RadioWorker command handling with fake network clients."""

import time

from radiowall.places_db import Place
from radiowall.radio import Next, PlayAt, RadioWorker, SetVolume, Stop
from radiowall.radio_garden import Station
from radiowall.state import MAX_CITIES, AppState, Phase, Session, Snapshot


def _place(pid, name="City", lat=0.0, lon=0.0):
    return Place(id=pid, lat100=int(lat * 100), lon100=int(lon * 100),
                 name=name, country="Xx")


def _stations(n, prefix="S"):
    return [Station(id=f"{prefix}{i}", title=f"{prefix} {i}") for i in range(n)]


# --- Session ---------------------------------------------------------------

def test_session_cycles_stations():
    s = Session(48.0, 16.0, _place("p1"), _stations(3))
    assert [s.advance().id for _ in range(3)] == ["S0", "S1", "S2"]
    assert s.exhausted


def test_session_advance_moves_cursor_even_on_caller_failure():
    # advance() commits the skip; a failed resolve must not replay the
    # same station on the next NEXT (ESP32 parity).
    s = Session(0, 0, _place("p1"), _stations(2))
    first = s.advance()
    second = s.advance()
    assert first.id != second.id
    assert s.exhausted


def test_session_enter_city_keeps_origin_and_visited():
    s = Session(48.0, 16.0, _place("p1"), _stations(1))
    s.advance()
    s.enter_city(_place("p2"), _stations(2))
    assert s.origin_lat == 48.0            # hop measured from touch origin
    assert s.visited == {"p1", "p2"}
    assert s.playing_index == -1
    assert not s.exhausted


def test_session_hop_cap():
    s = Session(0, 0, _place("p0"), [])
    for i in range(1, MAX_CITIES):
        s.enter_city(_place(f"p{i}"), [])
    assert not s.can_hop
    assert len(s.visited) == MAX_CITIES


# --- AppState ----------------------------------------------------------------

def test_snapshot_is_isolated_copy():
    st = AppState()
    st.set_playing("Vienna", "AT", "Radio", 1, 5)
    snap = st.snapshot()
    st.set_idle()
    assert snap.phase == Phase.PLAYING     # old snapshot unaffected
    assert st.snapshot().phase == Phase.IDLE


def test_status_expires():
    st = AppState()
    st.set_status("Oops", ttl_s=0.05)
    assert st.snapshot().status_text == "Oops"
    time.sleep(0.08)
    assert st.snapshot().status_text == ""


def test_volume_clamped_and_flash():
    st = AppState()
    assert st.bump_volume(+200) == 100
    assert st.bump_volume(-300) == 0
    assert st.snapshot().volume_flash is True


def test_set_idle_preserves_volume():
    st = AppState()
    st.bump_volume(+10)  # 50 -> 60
    st.set_playing("A", "B", "C", 1, 1)
    st.set_idle()
    assert st.snapshot().volume == 60


# --- RadioWorker with fakes ---------------------------------------------------

class FakeRG:
    def __init__(self, stations_by_place, resolve_fail_ids=()):
        self.by_place = stations_by_place
        self.resolve_fail = set(resolve_fail_ids)

    def get_stations(self, place_id):
        return self.by_place.get(place_id, [])

    def resolve_stream_url(self, station_id):
        if station_id in self.resolve_fail:
            return None
        return f"http://stream/{station_id}"


class FakeWiim:
    def __init__(self):
        self.played = []
        self.volumes = []
        self.stopped = 0

    def play(self, url):
        self.played.append(url)
        return True

    def stop(self):
        self.stopped += 1
        return True

    def set_volume(self, v):
        self.volumes.append(v)
        return True

    def get_volume(self):
        return 40


class FakePlaces:
    """Two cities 1 apart; p2 is nearer to (0,0) than p3."""

    def __init__(self):
        self.p1 = _place("p1", "Alpha", 0.0, 0.0)
        self.p2 = _place("p2", "Beta", 0.0, 1.0)
        self.p3 = _place("p3", "Gamma", 0.0, 2.0)
        self.all = [self.p1, self.p2, self.p3]

    def find_nearest(self, lat, lon):
        return self.find_nearest_excluding(lat, lon, set())

    def find_nearest_excluding(self, lat, lon, exclude):
        candidates = [p for p in self.all if p.id not in exclude]
        if not candidates:
            return None
        return min(candidates, key=lambda p: (p.lat - lat) ** 2 + (p.lon - lon) ** 2)


def _worker(rg, wiim=None):
    state = AppState()
    w = RadioWorker(state, FakePlaces(), rg=rg, wiim=wiim or FakeWiim(),
                    use_decoder=False)
    w.start()
    return state, w


def _drain(w, timeout=2.0):
    deadline = time.time() + timeout
    while not w._queue.empty() and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.15)  # let the in-flight command finish


def test_play_at_plays_nearest_city_first_station():
    rg = FakeRG({"p1": _stations(2, "a")})
    state, w = _worker(rg)
    try:
        w.submit(PlayAt(0.0, 0.0))
        _drain(w)
        snap = state.snapshot()
        assert snap.phase == Phase.PLAYING
        assert snap.place_name == "Alpha"
        assert snap.station_title == "a 0"
        assert (snap.station_index, snap.station_total) == (1, 2)
    finally:
        w.stop()


def test_next_cycles_then_hops_from_origin():
    rg = FakeRG({"p1": _stations(1, "a"), "p2": _stations(1, "b")})
    state, w = _worker(rg)
    try:
        w.submit(PlayAt(0.0, 0.0))     # plays a0 (Alpha, only station)
        w.submit(Next())               # Alpha exhausted -> hop to Beta -> b0
        _drain(w)
        snap = state.snapshot()
        assert snap.place_name == "Beta"
        assert snap.station_title == "b 0"
    finally:
        w.stop()


def test_resolve_failure_skips_station():
    rg = FakeRG({"p1": _stations(3, "a")}, resolve_fail_ids={"a1"})
    wiim = FakeWiim()
    state, w = _worker(rg, wiim)
    try:
        w.submit(PlayAt(0.0, 0.0))     # a0 plays
        w.submit(Next())               # a1 fails to resolve -> status, skip
        _drain(w)
        w.submit(Next())               # a2 plays
        _drain(w)
        assert state.snapshot().station_title == "a 2"
        assert [u.rsplit("/", 1)[1] for u in wiim.played] == ["a0", "a2"]
    finally:
        w.stop()


def test_stop_goes_idle_and_stops_wiim():
    rg = FakeRG({"p1": _stations(1, "a")})
    wiim = FakeWiim()
    state, w = _worker(rg, wiim)
    try:
        w.submit(PlayAt(0.0, 0.0))
        w.submit(Stop())
        _drain(w)
        assert state.snapshot().phase == Phase.IDLE
        assert wiim.stopped >= 1
    finally:
        w.stop()


def test_volume_debounced_to_last_value():
    rg = FakeRG({})
    wiim = FakeWiim()
    state, w = _worker(rg, wiim)
    try:
        for v in (41, 42, 43, 44, 45):
            w.submit(SetVolume(v))
        time.sleep(0.5)                # > debounce window
        assert wiim.volumes == [45]    # only the final value hit the WiiM
    finally:
        w.stop()


def test_no_stations_in_city_sets_status():
    rg = FakeRG({})                    # every city has zero stations
    state, w = _worker(rg)
    try:
        w.submit(PlayAt(0.0, 0.0))
        _drain(w)
        snap = state.snapshot()
        assert snap.phase == Phase.IDLE
        assert snap.status_text == "No stations found"
    finally:
        w.stop()
