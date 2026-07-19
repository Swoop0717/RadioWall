"""Config store, wifi nmcli parsing, SSDP XML matching, VERY_LONG
gesture, and the SetupUI state machine (no hardware, no network —
network entry points are monkeypatched)."""

import json
import time

import pytest

from radiowall import config, wifi
from radiowall.discovery import Speaker, _probe_location, _xml_tag
from radiowall.input.gestures import Gesture, GestureDetector


# --- config store -----------------------------------------------------------

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOWALL_CONFIG", str(tmp_path / "config.json"))
    config.reset_cache_for_tests()
    yield config
    config.reset_cache_for_tests()


def test_config_roundtrip(cfg):
    assert cfg.get("wiim_ip") is None
    cfg.set("wiim_ip", "192.168.0.63")
    assert cfg.get("wiim_ip") == "192.168.0.63"
    # persisted, not just cached
    config.reset_cache_for_tests()
    assert cfg.get("wiim_ip") == "192.168.0.63"


def test_config_survives_corrupt_file(cfg, tmp_path):
    (tmp_path / "config.json").write_text("{not json")
    config.reset_cache_for_tests()
    assert cfg.get("anything") is None
    cfg.set("k", 1)                       # still writable
    assert json.loads((tmp_path / "config.json").read_text())["k"] == 1


# --- wifi nmcli parsing -------------------------------------------------------

def _fake_run(responses):
    def run(args):
        key = " ".join(args[:5])
        for pattern, out in responses.items():
            if pattern in key:
                return 0, out, ""
        return 1, "", "unexpected: " + key
    return run


def test_wifi_scan_parses_dedupes_and_sorts():
    run = _fake_run({
        "nmcli -t -f SSID,SIGNAL,SECURITY": (
            "HomeNet:82:WPA2\n"
            "HomeNet:45:WPA2\n"           # weaker duplicate BSS
            "Cafe\\: Free:60:\n"          # escaped colon, open
            ":30:WPA2\n"                  # hidden — skipped
        ),
        "nmcli -t -f NAME,TYPE": "HomeNet:802-11-wireless\nWired:ethernet\n",
    })
    nets = wifi.scan(run)
    assert [n.ssid for n in nets] == ["HomeNet", "Cafe: Free"]
    assert nets[0].signal == 82
    assert nets[0].known and nets[0].secured
    assert not nets[1].secured and not nets[1].known


def test_wifi_connect_uses_profile_for_known_ssid():
    calls = []

    def run(args):
        calls.append(args)
        if args[:3] == ["nmcli", "-t", "-f"]:
            return 0, "HomeNet:802-11-wireless\n", ""
        return 0, "Connection successfully activated", ""

    ok, msg = wifi.connect("HomeNet", None, run)
    assert ok
    assert ["nmcli", "connection", "up", "id", "HomeNet"] in calls


def test_wifi_connect_new_network_passes_password():
    calls = []

    def run(args):
        calls.append(args)
        if args[:3] == ["nmcli", "-t", "-f"]:
            return 0, "", ""
        return 0, "ok", ""

    wifi.connect("NewNet", "hunter22", run)
    assert ["nmcli", "device", "wifi", "connect", "NewNet",
            "password", "hunter22"] in calls


# --- discovery XML matching ---------------------------------------------------

_WIIM_XML = """<?xml version="1.0"?>
<root><device>
  <friendlyName>Wiim Amp</friendlyName>
  <manufacturer>Linkplay Technology Inc.</manufacturer>
</device></root>"""


def test_xml_tag_extraction():
    assert _xml_tag(_WIIM_XML, "friendlyName") == "Wiim Amp"
    assert _xml_tag(_WIIM_XML, "missing") == ""


def test_probe_location_filters_non_linkplay(monkeypatch):
    import radiowall.discovery as disco

    class Resp:
        def __init__(self, text):
            self.text = text

    monkeypatch.setattr(disco.requests, "get",
                        lambda url, timeout: Resp(_WIIM_XML))
    sp = _probe_location("http://192.168.0.33:49152/description.xml")
    assert sp == Speaker(name="Wiim Amp", ip="192.168.0.33")

    monkeypatch.setattr(disco.requests, "get",
                        lambda url, timeout: Resp("<root>a router</root>"))
    assert _probe_location("http://192.168.0.1:80/desc.xml") is None


# --- VERY_LONG gesture ----------------------------------------------------------

def test_very_long_fires_after_long_while_held():
    det = GestureDetector()
    t = 100.0
    assert det.update([(t, True)], t) == []
    assert det.update([], t + 0.9) == [Gesture.LONG]
    assert det.update([], t + 2.9) == []
    assert det.update([], t + 3.1) == [Gesture.VERY_LONG]
    # release is swallowed — no SHORT afterwards
    assert det.update([(t + 3.3, False)], t + 3.3) == []
    assert det.update([], t + 4.0) == []


# --- SetupUI state machine -------------------------------------------------------

@pytest.fixture
def ui(cfg, monkeypatch):
    from radiowall.display import setup_ui as su

    class FakeWorker:
        def __init__(self):
            self.wiim_ips = []

        def set_wiim(self, ip):
            self.wiim_ips.append(ip)

    monkeypatch.setattr(su.discovery, "discover",
                        lambda **kw: [Speaker("Wiim Amp", "192.168.0.33"),
                                      Speaker("Esszimmer", "192.168.0.63")])
    monkeypatch.setattr(su.wifi, "scan", lambda: [
        wifi.Network("HomeNet", 80, True, known=True),
        wifi.Network("NewNet", 60, True, known=False),
    ])
    monkeypatch.setattr(su.wifi, "connect",
                        lambda ssid, pw: (True, f"{ssid}/{pw}"))
    monkeypatch.setattr(su.wifi, "status", lambda: ("HomeNet", "10.0.0.5"))
    worker = FakeWorker()
    u = su.SetupUI(worker)
    u.open()
    return u, worker


def _wait_items(u, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with u._lock:
            if u._items and u._busy is None:
                return
        time.sleep(0.01)
    raise AssertionError("setup task did not deliver items")


def _into_setup(u):
    """Root menu → Setup submenu (Setup sits at index 3)."""
    u.handle_rotate(+3)
    u.handle_short()


def test_setup_speaker_pick_saves_and_applies(ui, cfg):
    u, worker = ui
    _into_setup(u)
    u.handle_short()                       # SETUP: Speaker (cursor 0)
    _wait_items(u)
    u.handle_rotate(+1)                    # second speaker
    u.handle_short()
    assert cfg.get("wiim_ip") == "192.168.0.63"
    assert cfg.get("wiim_name") == "Esszimmer"
    assert worker.wiim_ips == ["192.168.0.63"]
    assert u._screen == "MENU"


def test_setup_wifi_password_entry_flow(ui, cfg):
    u, _ = ui
    _into_setup(u)
    u.handle_rotate(+2)                    # SETUP → WiFi
    u.handle_short()
    _wait_items(u)
    u.handle_rotate(+1)                    # NewNet (unknown, secured)
    u.handle_short()
    assert u._screen == "PASSWORD"
    # type "ab": strip starts on 'a'
    u.handle_short()                       # 'a'
    u.handle_rotate(+1)                    # 'b'
    u.handle_short()
    assert u._pw_text == "ab"
    u.handle_double()                      # backspace
    assert u._pw_text == "a"
    u.handle_rotate(-1 - len("a"))         # back to [OK] ... position math:
    u._pw_pos = 0                          # jump straight to [OK] for the test
    u.handle_short()
    _wait_items(u)
    with u._lock:
        ok, detail = u._items[0]
    assert ok and detail == "NewNet/a"


def test_setup_known_network_connects_without_password(ui):
    u, _ = ui
    _into_setup(u)
    u.handle_rotate(+2)
    u.handle_short()                       # WiFi
    _wait_items(u)
    u.handle_short()                       # HomeNet (known)
    _wait_items(u)
    with u._lock:
        ok, detail = u._items[0]
    assert ok and detail == "HomeNet/None"


def test_setup_calibration_two_taps(ui, cfg):
    u, _ = ui
    _into_setup(u)
    u.handle_rotate(+3)                    # Touch calibration
    u.handle_short()
    assert u._screen == "CALIB"
    u.handle_tap(0.91, 0.88)               # corners in either order
    u.handle_tap(0.12, 0.15)
    cal = cfg.get("touch_calib")
    assert cal == {"x0": 0.12, "y0": 0.15, "x1": 0.91, "y1": 0.88}


def test_setup_calibration_rejects_degenerate_rect(ui, cfg):
    u, _ = ui
    _into_setup(u)
    u.handle_rotate(+3)
    u.handle_short()
    u.handle_tap(0.5, 0.5)
    u.handle_tap(0.52, 0.9)                # x too close → restart
    assert cfg.get("touch_calib") is None
    assert u._calib_stage == 0


def test_setup_long_press_backs_out_level_by_level(ui):
    u, _ = ui
    _into_setup(u)
    u.handle_short()                       # into Speaker
    u.handle_long()                        # back to Setup submenu
    assert u._screen == "SETUP_MENU" and u.active
    u.handle_long()                        # back to root menu
    assert u._screen == "MENU" and u.active
    u.handle_long()                        # close
    assert not u.active


# --- needs_animation (smart redraw) ------------------------------------------

def test_needs_animation():
    from radiowall.display import fonts, screens
    from radiowall.state import Phase, Snapshot

    class Dev:
        width, height = 256, 64

    fs = fonts.fonts_for(64)
    dev = Dev()
    na = screens.needs_animation
    assert not na(Snapshot(), dev, fs)                        # idle
    assert na(Snapshot(phase=Phase.LOADING), dev, fs)         # dots
    assert na(Snapshot(volume_flash=True), dev, fs)           # flash
    short = Snapshot(phase=Phase.PLAYING, station_title="FM4")
    assert not na(short, dev, fs)                             # centered
    long_ = Snapshot(phase=Phase.PLAYING, station_title=(
        "Rás 2 — Icelandic public radio with a very long name"))
    assert na(long_, dev, fs)                                 # scrolls


def test_setup_sleep_dial_slow_steps_10min(ui):
    import time as _t

    u, worker = ui
    worker.sleep_minutes = []
    worker.set_sleep_timer = worker.sleep_minutes.append
    u.handle_short()                       # MENU: Sleep timer (cursor 0)
    assert u._screen == "SLEEP"
    for _ in range(3):                     # slow detents → 10 min each
        u.handle_rotate(+1)
        _t.sleep(0.1)
    u.handle_rotate(-1)                    # back down one step
    assert u._sleep_min == 20
    u.handle_short()
    assert worker.sleep_minutes == [20]
    assert u._screen == "MENU"


def test_setup_sleep_dial_fast_spin_accelerates(ui):
    u, worker = ui
    worker.sleep_minutes = []
    worker.set_sleep_timer = worker.sleep_minutes.append
    u.handle_short()
    for _ in range(12):                    # rapid spin, no delay between
        u.handle_rotate(+1)
    # first detent 10 min, the rest at the fast 30 min step
    assert u._sleep_min == 10 + 11 * 30
    u.handle_rotate(-100)                  # spin to zero clamps at Off
    assert u._sleep_min == 0


def test_setup_sleep_dial_reopens_with_armed_time(ui):
    u, worker = ui
    worker.sleep_minutes_left = lambda: 42
    u.handle_short()
    assert u._sleep_min == 50              # rounded up to the 10-min grid


# --- history / favorites in the menu ------------------------------------------

def test_menu_history_play_and_star(ui, monkeypatch):
    from radiowall import history
    from radiowall.history import Entry

    history.reset_cache_for_tests()
    history.add(Entry(station_id="s1", station_title="Radio Wien",
                      place_id="p1", place_name="Vienna", country="AT",
                      lat=48.2, lon=16.4))
    history.add(Entry(station_id="s2", station_title="FM4",
                      place_id="p1", place_name="Vienna", country="AT",
                      lat=48.2, lon=16.4))

    u, worker = ui
    worker.played_entries = []
    worker.play_history = worker.played_entries.append

    u.handle_rotate(+1)                    # History
    u.handle_short()
    assert u._screen == "HISTORY"
    u.handle_rotate(+1)                    # older entry: Radio Wien
    u.handle_double()                      # star it
    assert history.entries(favorites_only=True)[0].station_id == "s1"
    u.handle_short()                       # play it
    assert worker.played_entries[0].station_id == "s1"
    assert not u.active                    # menu closed to show playback

    u.open()
    u.handle_rotate(+2)                    # Favorites
    u.handle_short()
    assert u._screen == "FAVORITES"
    u.handle_double()                      # unstar from favorites view
    assert history.entries(favorites_only=True) == []
    history.reset_cache_for_tests()


# --- band text (ICY track titles) ---------------------------------------------

def test_band_text_combines_station_and_track():
    from radiowall.display.screens import band_text
    from radiowall.state import Phase, Snapshot

    plain = Snapshot(phase=Phase.PLAYING, station_title="FM4")
    assert band_text(plain) == "FM4"         # no track → unchanged layout
    with_track = Snapshot(phase=Phase.PLAYING, station_title="FM4",
                          track_title="Kraftwerk - Autobahn")
    assert band_text(with_track) == "FM4  ·  Kraftwerk - Autobahn"
    echo = Snapshot(phase=Phase.PLAYING, station_title="FM4",
                    track_title="fm4")       # station name echoed back
    assert band_text(echo) == "FM4"


# --- pixel shift ---------------------------------------------------------------

def test_pixel_shift_orbits_and_moves_content(monkeypatch):
    from PIL import Image
    from radiowall.display import pixel_shift as ps

    # orbit covers 4 distinct positions, one step per period
    offs = {ps.offset_at(i * ps.PERIOD_S + 1) for i in range(4)}
    assert offs == {(0, 0), (1, 0), (1, 1), (0, 1)}

    class Dev:
        def __init__(self):
            self.shown = None

        def display(self, img):
            self.shown = img

    monkeypatch.delenv("RADIOWALL_PIXEL_SHIFT", raising=False)
    dev = Dev()
    ps.install_pixel_shift(dev, default_on=True)
    img = Image.new("RGB", (8, 8))
    img.putpixel((0, 0), (255, 0, 0))

    monkeypatch.setattr(ps.time, "monotonic", lambda: ps.PERIOD_S * 2 + 1)
    dev.display(img)                       # orbit position (1, 1)
    assert dev.shown.getpixel((1, 1)) == (255, 0, 0)
    assert dev.shown.getpixel((0, 0)) == (0, 0, 0)


def test_pixel_shift_env_disable(monkeypatch):
    from radiowall.display import pixel_shift as ps

    class Dev:
        def display(self, img):
            pass

    monkeypatch.setenv("RADIOWALL_PIXEL_SHIFT", "0")
    dev = Dev()
    ps.install_pixel_shift(dev, default_on=True)
    assert "display" not in dev.__dict__   # no wrapper installed


# --- multiroom -----------------------------------------------------------------

def test_linkplay_multiroom_command_formats(monkeypatch):
    from radiowall.linkplay import LinkPlay

    calls = []
    lp = LinkPlay("10.0.0.9")

    def fake_request(cmd, retries=2):
        calls.append(cmd)
        if cmd == "multiroom:getSlaveList":
            return ('{"slaves":1,"slave_list":[{"name":"Esszimmer",'
                    '"ip":"10.0.0.7"}]}')
        return "OK"

    monkeypatch.setattr(lp, "_request", fake_request)
    assert lp.get_slave_ips() == ["10.0.0.7"]
    assert lp.join_master("10.0.0.9")
    assert lp.kick_slave("10.0.0.7")
    assert lp.ungroup()
    assert "ConnectMasterAp:JoinGroupMaster:eth10.0.0.9:wifi0.0.0.0" in calls
    assert "multiroom:SlaveKickout:10.0.0.7" in calls
    assert "multiroom:Ungroup" in calls


def test_speaker_screen_group_toggle(ui, cfg, monkeypatch):
    from radiowall.display import setup_ui as su

    cfg.set("wiim_ip", "192.168.0.33")     # Wiim Amp is main

    actions = []

    class FakeLP:
        def __init__(self, ip):
            self.ip = ip

        def get_slaves(self):
            joined = any(a == ("join", "192.168.0.63") for a in actions)
            kicked = any(a[0] == "kick" for a in actions)
            if joined and not kicked:
                return [("Esszimmer", "192.168.0.63")]
            return []

        def join_master(self, master_ip):
            actions.append(("join", self.ip))
            return True

        def kick_slave(self, ip):
            actions.append(("kick", ip))
            return True

    monkeypatch.setattr(su, "LinkPlay", FakeLP)
    u, worker = ui
    _into_setup(u)
    u.handle_short()                       # Speaker
    _wait_items(u)
    with u._lock:
        assert u._items[0][1] is True      # Wiim Amp marked as main
        assert u._items[1][2] is False     # Esszimmer not grouped
    u.handle_rotate(+1)                    # Esszimmer
    u.handle_double()                      # group it
    _wait_items(u)
    assert ("join", "192.168.0.63") in actions
    with u._lock:
        assert u._items[1][2] is True      # now shown grouped
    u.handle_double()                      # ungroup
    _wait_items(u)
    assert ("kick", "192.168.0.63") in actions


def test_speaker_pick_main_is_noop(ui, cfg, monkeypatch):
    from radiowall.display import setup_ui as su

    cfg.set("wiim_ip", "192.168.0.33")

    class FakeLP:
        def __init__(self, ip):
            pass

        def get_slaves(self):
            return []

    monkeypatch.setattr(su, "LinkPlay", FakeLP)
    u, worker = ui
    _into_setup(u)
    u.handle_short()
    _wait_items(u)
    u.handle_short()                       # press on the main speaker
    assert u._screen == "SPEAKER"          # stays put, no re-set
    assert worker.wiim_ips == []


def test_grouped_slave_hidden_from_ssdp_still_listed(ui, cfg, monkeypatch):
    """Grouped slaves stop announcing via SSDP — the master's slave
    list must fill the gap or they can never be ungrouped again."""
    from radiowall.display import setup_ui as su

    cfg.set("wiim_ip", "192.168.0.33")
    # discovery only sees the master now
    monkeypatch.setattr(su.discovery, "discover",
                        lambda: [Speaker("Wiim Amp", "192.168.0.33")])

    class FakeLP:
        def __init__(self, ip):
            self.ip = ip

        def get_slaves(self):
            return [("Esszimmer", "192.168.0.63")]

        def kick_slave(self, ip):
            return True

    monkeypatch.setattr(su, "LinkPlay", FakeLP)
    u, _ = ui
    _into_setup(u)
    u.handle_short()                       # Speaker
    _wait_items(u)
    with u._lock:
        ips = [(sp.ip, grouped) for sp, _m, grouped in u._items]
    assert ("192.168.0.63", True) in ips   # slave visible and marked


# --- bluetooth speaker ----------------------------------------------------------

def test_bt_screen_pick_sets_output_and_worker(ui, cfg, monkeypatch):
    from radiowall import btaudio
    from radiowall.btaudio import BtDevice

    monkeypatch.setattr(btaudio, "scan", lambda: [
        BtDevice("AA:BB:CC:DD:EE:FF", "JBL Flip", paired=True),
        BtDevice("11:22:33:44:55:66", "Soundcore"),
    ])
    monkeypatch.setattr(btaudio, "connect",
                        lambda mac: (True, "connected"))

    u, worker = ui
    worker.bt = []
    worker.set_bt = lambda mac, name: worker.bt.append((mac, name))
    _into_setup(u)
    u.handle_rotate(+1)                    # Speaker (BT)
    u.handle_short()
    assert u._screen == "BTSPEAKER"
    _wait_items(u)
    u.handle_short()                       # JBL Flip (sorted first: paired)
    _wait_items(u)
    assert cfg.get("output") == "bt"
    assert cfg.get("bt_mac") == "AA:BB:CC:DD:EE:FF"
    assert worker.bt == [("AA:BB:CC:DD:EE:FF", "JBL Flip")]


def test_bt_forget_active_output_falls_back_to_wiim(ui, cfg, monkeypatch):
    from radiowall import btaudio
    from radiowall.btaudio import BtDevice

    cfg.set("output", "bt")
    cfg.set("bt_mac", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setattr(btaudio, "scan", lambda: [
        BtDevice("AA:BB:CC:DD:EE:FF", "JBL Flip", paired=True)])
    monkeypatch.setattr(btaudio, "forget", lambda mac: True)

    u, _ = ui
    _into_setup(u)
    u.handle_rotate(+1)
    u.handle_short()
    _wait_items(u)
    with u._lock:
        assert u._items[0][1] is True      # marked as active output
    u.handle_double()                      # forget it
    _wait_items(u)
    assert cfg.get("output") == "wiim"


def test_btaudio_parsing_filters_nameless():
    from radiowall.btaudio import _parse_devices

    out = ("Device AA:BB:CC:DD:EE:FF JBL Flip 5\n"
           "Device 4C:57:91:0C:E6:20 4C-57-91-0C-E6-20\n"
           "garbage line\n")
    d = _parse_devices(out)
    assert d == {"AA:BB:CC:DD:EE:FF": "JBL Flip 5"}


def test_worker_output_selection_from_config(cfg, monkeypatch):
    from radiowall.radio import RadioWorker
    from radiowall.btplayer import BtPlayer
    from radiowall.linkplay import LinkPlay

    monkeypatch.delenv("RADIOWALL_WIIM_IP", raising=False)
    cfg.set("output", "bt")
    cfg.set("bt_mac", "AA:BB:CC:DD:EE:FF")
    cfg.set("bt_name", "JBL Flip")
    out = RadioWorker._make_output()
    assert isinstance(out, BtPlayer) and out.mac == "AA:BB:CC:DD:EE:FF"

    cfg.set("output", "wiim")
    cfg.set("wiim_ip", "192.168.0.33")
    out = RadioWorker._make_output()
    assert isinstance(out, LinkPlay) and out.ip == "192.168.0.33"


def test_bt_pick_wiim_switches_linkplay_input(ui, cfg, monkeypatch):
    """A WiiM used as BT sink keeps listening to WiFi — picking it must
    flip its input to bluetooth via LinkPlay."""
    from radiowall import btaudio
    from radiowall.btaudio import BtDevice
    from radiowall.display import setup_ui as su

    monkeypatch.setattr(btaudio, "scan", lambda: [
        BtDevice("54:78:C9:E5:05:FD", "Wiim Amp", paired=True)])
    monkeypatch.setattr(btaudio, "connect", lambda mac: (True, "connected"))

    switched = []

    class FakeLP:
        def __init__(self, ip):
            self.ip = ip

        def switch_mode(self, mode):
            switched.append((self.ip, mode))
            return True

        def get_volume(self):
            return 28                      # the near-silent trap

        def set_volume(self, v):
            switched.append((self.ip, f"vol{v}"))
            return True

        def get_slaves(self):
            return []

    monkeypatch.setattr(su, "LinkPlay", FakeLP)
    u, worker = ui
    worker.set_bt = lambda mac, name: None
    _into_setup(u)
    u.handle_rotate(+1)
    u.handle_short()                       # Speaker (BT)
    _wait_items(u)
    u.handle_short()                       # Wiim Amp
    _wait_items(u)
    # discovery fixture lists "Wiim Amp" at 192.168.0.33 → input switched
    # and the too-low device volume raised to the audible baseline
    assert switched == [("192.168.0.33", "bluetooth"),
                        ("192.168.0.33", "vol45")]


def test_output_swap_closes_previous_bt_player(cfg, monkeypatch):
    """An orphaned BtPlayer keeps the exclusive bluealsa PCM open and
    starves its successor ('Device or resource busy')."""
    from radiowall import btplayer
    from radiowall.radio import RadioWorker
    from radiowall.state import AppState

    closed = []

    class FakeBt:
        def __init__(self, mac, name=""):
            self.mac, self.name = mac, name

        def close(self):
            closed.append(self.mac)

    monkeypatch.setattr(btplayer, "BtPlayer", FakeBt)

    from tests.test_state import FakeRG, FakeWiim, FakePlaces
    w = RadioWorker(AppState(), FakePlaces(), rg=FakeRG({}), wiim=FakeWiim(),
                    use_decoder=False)
    w.set_bt("AA:BB:CC:DD:EE:FF", "One")
    w.set_bt("11:22:33:44:55:66", "Two")   # must close One
    w.set_wiim("192.168.0.33")             # must close Two
    assert closed == ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]


def test_output_swap_transfers_playing_station(cfg, monkeypatch):
    """Picking a different speaker mid-play must move the music there,
    not leave the new speaker silent under a stale PLAYING screen."""
    import radiowall.radio as radio_mod
    from radiowall.radio import RadioWorker, PlayAt
    from radiowall.state import AppState, Phase

    from tests.test_state import FakeRG, FakeWiim, FakePlaces, _stations

    new_speaker = FakeWiim()

    class FakeLP2:
        def __init__(self, ip):
            self.ip = ip

        def play(self, url):
            new_speaker.played.append(url)
            return True

    monkeypatch.setattr(radio_mod, "LinkPlay", FakeLP2)

    rg = FakeRG({"p1": _stations(1)})
    old_speaker = FakeWiim()
    state = AppState()
    w = RadioWorker(state, FakePlaces(), rg=rg, wiim=old_speaker,
                    use_decoder=False)
    w.start()
    try:
        w.submit(PlayAt(0.0, 0.0))
        deadline = time.time() + 2.0
        while not old_speaker.played and time.time() < deadline:
            time.sleep(0.02)
        w.set_wiim("192.168.0.99")         # switch output mid-play
        deadline = time.time() + 2.0
        while not new_speaker.played and time.time() < deadline:
            time.sleep(0.02)
        assert new_speaker.played == old_speaker.played  # same stream URL
        assert state.snapshot().phase == Phase.PLAYING
    finally:
        w.stop()


def test_band_text_filters_junk_icy_titles():
    from radiowall.display.screens import band_text
    from radiowall.state import Phase, Snapshot

    def snap(track):
        return Snapshot(phase=Phase.PLAYING, station_title="Radio Shabelle",
                        track_title=track)

    for junk in ("-", " - ", "--", "...", "***", "Unknown", "n/a",
                 "NULL", "Untitled", ""):
        assert band_text(snap(junk)) == "Radio Shabelle", junk
    assert band_text(snap("K'naan - Wavin' Flag")) \
        == "Radio Shabelle  ·  K'naan - Wavin' Flag"


# --- touch test screen ----------------------------------------------------------

def test_touch_test_resolves_without_playing(ui, cfg, monkeypatch):
    from radiowall.display import setup_ui as su
    from tests.test_state import FakePlaces

    u, worker = ui
    u._places = FakePlaces()
    worker.played = []
    _into_setup(u)
    u.handle_rotate(+4)                    # Touch test
    u.handle_short()
    assert u._screen == "TOUCHTEST"
    # identity calibration: (0.5, 0.25) → lon 0, lat 45
    u.handle_tap(0.5, 0.25)
    x, y, lat, lon, name, _country, dist = u._tt_last
    assert (lat, lon) == (45.0, 0.0)
    assert name == "Alpha"                 # nearest FakePlace to (45, 0)
    assert dist > 0
    assert worker.played == []             # nothing was played


def test_touch_test_respects_saved_calibration(ui, cfg):
    from tests.test_state import FakePlaces

    u, _ = ui
    u._places = FakePlaces()
    # map occupies the middle half of the frame in both axes
    cfg.set("touch_calib", {"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75})
    _into_setup(u)
    u.handle_rotate(+4)
    u.handle_short()
    u.handle_tap(0.5, 0.5)                 # frame center = map center
    _x, _y, lat, lon, *_ = u._tt_last
    assert (lat, lon) == (0.0, 0.0)
