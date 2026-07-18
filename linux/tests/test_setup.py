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
                        lambda: [Speaker("Wiim Amp", "192.168.0.33"),
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


def test_setup_speaker_pick_saves_and_applies(ui, cfg):
    u, worker = ui
    u.handle_short()                       # MENU: Speaker (cursor 0)
    _wait_items(u)
    u.handle_rotate(+1)                    # second speaker
    u.handle_short()
    assert cfg.get("wiim_ip") == "192.168.0.63"
    assert cfg.get("wiim_name") == "Esszimmer"
    assert worker.wiim_ips == ["192.168.0.63"]
    assert u._screen == "MENU"


def test_setup_wifi_password_entry_flow(ui, cfg):
    u, _ = ui
    u.handle_rotate(+1)                    # MENU → WiFi
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
    u.handle_rotate(+1)
    u.handle_short()                       # WiFi
    _wait_items(u)
    u.handle_short()                       # HomeNet (known)
    _wait_items(u)
    with u._lock:
        ok, detail = u._items[0]
    assert ok and detail == "HomeNet/None"


def test_setup_calibration_two_taps(ui, cfg):
    u, _ = ui
    u.handle_rotate(+3)                    # Touch calibration
    u.handle_short()
    assert u._screen == "CALIB"
    u.handle_tap(0.91, 0.88)               # corners in either order
    u.handle_tap(0.12, 0.15)
    cal = cfg.get("touch_calib")
    assert cal == {"x0": 0.12, "y0": 0.15, "x1": 0.91, "y1": 0.88}


def test_setup_calibration_rejects_degenerate_rect(ui, cfg):
    u, _ = ui
    u.handle_rotate(+3)
    u.handle_short()
    u.handle_tap(0.5, 0.5)
    u.handle_tap(0.52, 0.9)                # x too close → restart
    assert cfg.get("touch_calib") is None
    assert u._calib_stage == 0


def test_setup_long_press_backs_out_and_exits(ui):
    u, _ = ui
    u.handle_short()                       # into Speaker
    u.handle_long()                        # back to menu
    assert u._screen == "MENU" and u.active
    u.handle_long()                        # exit
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
    u.handle_rotate(+2)                    # MENU: Sleep timer
    u.handle_short()
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
    u.handle_rotate(+2)
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
    u.handle_rotate(+2)
    u.handle_short()
    assert u._sleep_min == 50              # rounded up to the 10-min grid
