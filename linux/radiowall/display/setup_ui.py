"""On-device menu — player controls AND setup, no phone needed.

Entered by holding the encoder ~0.8 s (Gesture.LONG); music keeps
playing underneath. One knob drives everything: rotate = move / pick,
short press = select, long press = back (at the root: close). Holding
on to ~3 s (VERY_LONG) stops playback from anywhere.

Screens:
  MENU       Sleep timer · History · Favorites · Setup
  HISTORY    recently played stations; press = replay, 2x = star
  FAVORITES  starred history entries
  SLEEP      oven-style dial, 10/30-min steps
  SETUP_MENU Speaker (WiFi) · Speaker (BT) · WiFi · Touch calib · Info
  SPEAKER    SSDP-discover LinkPlay devices; press = make it the main
             speaker (● marker), 2x = join/remove it from the main
             speaker's multiroom group (+ marker)
  BTSPEAKER  bluetoothctl scan; press = pair+connect+use as output
             (the board decodes and streams via bluealsa/A2DP),
             2x = forget the device
  WIFI       nmcli scan, pick an SSID (known ones connect directly)
  PASSWORD   rotary character entry for WiFi passwords
  CALIB      tap top-left then bottom-right corner → config['touch_calib']
  TOUCHTEST  tap anywhere: shows the resolved city/lat/lon/raw coords
             through the SAVED calibration, plays nothing — the tool
             for verifying a freshly calibrated map print
  INFO       SSID, IP, configured speaker

All network work (discovery, scan, connect) runs on daemon threads;
the UI thread only reads the result slots. A generation counter makes
stale thread results harmless (user backed out and reopened). The
menu closes itself after 30 s without input — it sits over a playing
radio and must never strand the volume knob.

The class is UI-state only — display drawing happens in draw(), input
in handle_*(); both are called from the main loop. No hardware
dependencies, so the whole flow is unit-testable and emulator-friendly.
"""

from __future__ import annotations

import logging
import threading
import time

from luma.core.render import canvas

from radiowall import config, discovery, geo, history, wifi
from radiowall.display import fonts
from radiowall.linkplay import LinkPlay

log = logging.getLogger(__name__)

AMBER = (255, 176, 0)
AMBER_BRIGHT = (255, 210, 80)
AMBER_DIM = (110, 75, 0)
AMBER_GHOST = (60, 40, 0)

# Password entry: [OK] first, then the character ranges. Backspace is
# double-press and cancel is hold (same as everywhere else), so the only
# pseudo-key in the strip is the confirm — one detent left of 'a', and
# also adjacent to the symbols when the wrap comes around.
_PW_CONTROLS = ["[OK]"]
_PW_CHARS = (
    [chr(c) for c in range(ord("a"), ord("z") + 1)]
    + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [chr(c) for c in range(ord("0"), ord("9") + 1)]
    + list("!@#$%^&*()-_=+[]{};:'\",.<>/?\\|`~ ")
)
_PW_STRIP = _PW_CONTROLS + _PW_CHARS

# No Stop / Exit items: hold-to-3s stops from anywhere, hold-at-root
# closes — both already on the knob, both shown in the hint bar.
_MENU_ITEMS = ["Sleep timer", "History", "Favorites", "Setup"]
_SETUP_ITEMS = ["Speaker (WiFi)", "Speaker (BT)", "WiFi",
                "Touch calibration", "Touch test", "Info"]

# hold = back one level; at MENU it closes
_PARENT = {
    "SLEEP": "MENU", "HISTORY": "MENU", "FAVORITES": "MENU",
    "SETUP_MENU": "MENU",
    "SPEAKER": "SETUP_MENU", "BTSPEAKER": "SETUP_MENU",
    "WIFI": "SETUP_MENU", "WIFI_RESULT": "SETUP_MENU",
    "CALIB": "SETUP_MENU", "TOUCHTEST": "SETUP_MENU",
    "INFO": "SETUP_MENU",
}

_IDLE_CLOSE_S = 30.0

# Sleep dial: oven-timer feel. Slow turning steps 10 min per detent;
# once detents arrive faster than _SLEEP_FAST_S apart the step grows to
# 30 min, so 3 h is one confident spin, not 18 clicks.
_SLEEP_STEP_MIN = 10
_SLEEP_STEP_FAST_MIN = 30
_SLEEP_FAST_S = 0.08
_SLEEP_MAX_MIN = 720


class SetupUI:
    def __init__(self, worker=None, places=None) -> None:
        self._worker = worker
        self._places = places
        self.active = False
        self._screen = "MENU"
        self._cursor = 0
        self._gen = 0                    # invalidates in-flight threads
        self._lock = threading.Lock()
        self._busy: str | None = None    # spinner text while a thread runs
        self._notice: str | None = None  # transient result line
        self._notice_until = 0.0
        self._items: list = []           # current list screen payload
        self._pw_ssid = ""
        self._pw_text = ""
        self._pw_pos = len(_PW_CONTROLS)  # start on 'a', not on [OK]
        self._calib_stage = 0
        self._calib_first: tuple[float, float] | None = None
        self._tt_last: tuple | None = None   # touch-test result
        self._sleep_min = 0
        self._sleep_last_turn = 0.0
        self._last_input = 0.0

    # ---------- lifecycle ------------------------------------------------

    def open(self) -> None:
        self.active = True
        self._last_input = time.monotonic()
        self._goto("MENU")
        log.info("menu opened")

    def close(self) -> None:
        self.active = False
        self._gen += 1
        log.info("menu closed")

    def _goto(self, screen: str) -> None:
        self._screen = screen
        self._cursor = 0
        self._gen += 1
        with self._lock:
            self._busy = None
            self._items = []

    def _flash(self, text: str, seconds: float = 2.5) -> None:
        self._notice = text
        self._notice_until = time.monotonic() + seconds

    # ---------- async helpers --------------------------------------------

    def _spawn(self, label: str, fn) -> None:
        """Run fn() on a daemon thread; deliver its result to _items
        unless the user has navigated away meanwhile."""
        gen = self._gen
        with self._lock:
            self._busy = label

        def _run():
            try:
                result = fn()
            except Exception as e:          # network code must never kill UI
                log.warning("setup task failed: %s", e)
                result = e
            with self._lock:
                if gen != self._gen:
                    return                   # user left this screen
                self._busy = None
                if isinstance(result, Exception):
                    self._flash("Failed — see log")
                else:
                    self._items = result

        threading.Thread(target=_run, name="setup-task", daemon=True).start()

    # ---------- input ----------------------------------------------------

    def handle_rotate(self, delta: int) -> None:
        self._last_input = time.monotonic()
        if self._screen == "PASSWORD":
            self._pw_pos = (self._pw_pos + delta) % len(_PW_STRIP)
            return
        if self._screen == "SLEEP":
            now = time.monotonic()
            fast = (now - self._sleep_last_turn) < _SLEEP_FAST_S
            self._sleep_last_turn = now
            step = _SLEEP_STEP_FAST_MIN if fast else _SLEEP_STEP_MIN
            self._sleep_min = max(0, min(_SLEEP_MAX_MIN,
                                         self._sleep_min + delta * step))
            return
        n = self._item_count()
        if n:
            self._cursor = max(0, min(n - 1, self._cursor + delta))

    def handle_short(self) -> None:
        self._last_input = time.monotonic()
        if self._busy:
            return
        if self._screen == "MENU":
            self._menu_select(_MENU_ITEMS[self._cursor])
        elif self._screen == "SETUP_MENU":
            self._menu_select(_SETUP_ITEMS[self._cursor])
        elif self._screen == "SPEAKER":
            self._pick_speaker()
        elif self._screen == "BTSPEAKER":
            self._pick_bt()
        elif self._screen == "WIFI":
            self._pick_network()
        elif self._screen == "PASSWORD":
            self._pw_key()
        elif self._screen == "SLEEP":
            self._pick_sleep()
        elif self._screen in ("HISTORY", "FAVORITES"):
            self._play_entry()
        elif self._screen in ("INFO", "WIFI_RESULT"):
            self._goto(_PARENT.get(self._screen, "MENU"))

    def handle_long(self) -> None:
        """Back one level; at the root, close the menu."""
        self._last_input = time.monotonic()
        if self._screen == "MENU":
            self.close()
        elif self._screen == "PASSWORD":
            self._goto("WIFI")
            self._start_scan()
        else:
            self._goto(_PARENT.get(self._screen, "MENU"))

    def handle_double(self) -> None:
        self._last_input = time.monotonic()
        if self._screen == "PASSWORD":     # backspace shortcut
            self._pw_text = self._pw_text[:-1]
        elif self._screen in ("HISTORY", "FAVORITES"):
            self._toggle_star()
        elif self._screen == "SPEAKER":
            self._toggle_group()
        elif self._screen == "BTSPEAKER":
            self._forget_bt()

    def handle_tap(self, x: float, y: float) -> None:
        """Touch input while setup is open — calibration + touch test."""
        self._last_input = time.monotonic()
        if self._screen == "TOUCHTEST":
            self._tt_tap(x, y)
            return
        if self._screen != "CALIB":
            return
        if self._calib_stage == 0:
            self._calib_first = (x, y)
            self._calib_stage = 1
        elif self._calib_stage == 1:
            x0, y0 = self._calib_first
            if abs(x - x0) < 0.05 or abs(y - y0) < 0.05:
                self._flash("Corners too close — again")
                self._calib_stage = 0
                return
            calib = {"x0": min(x0, x), "y0": min(y0, y),
                     "x1": max(x0, x), "y1": max(y0, y)}
            config.set("touch_calib", calib)
            self._calib_stage = 2
            self._flash("Calibration saved")

    # ---------- per-screen logic ------------------------------------------

    def _item_count(self) -> int:
        if self._screen == "MENU":
            return len(_MENU_ITEMS)
        if self._screen == "SETUP_MENU":
            return len(_SETUP_ITEMS)
        with self._lock:
            return len(self._items)

    def _menu_select(self, item: str) -> None:
        if item == "History":
            self._goto("HISTORY")
            with self._lock:
                self._items = history.entries()
        elif item == "Favorites":
            self._goto("FAVORITES")
            with self._lock:
                self._items = history.entries(favorites_only=True)
        elif item == "Setup":
            self._goto("SETUP_MENU")
        elif item == "Speaker (WiFi)":
            self._goto("SPEAKER")
            self._spawn("Searching speakers", self._load_speakers)
        elif item == "Speaker (BT)":
            self._goto("BTSPEAKER")
            self._spawn("Scanning Bluetooth", self._load_bt)
        elif item == "WiFi":
            self._goto("WIFI")
            self._start_scan()
        elif item == "Sleep timer":
            self._goto("SLEEP")
            # start from the currently armed timer so reopening the
            # dial adjusts it instead of resetting to zero
            left = getattr(self._worker, "sleep_minutes_left", lambda: 0)()
            self._sleep_min = min(
                _SLEEP_MAX_MIN,
                (left + _SLEEP_STEP_MIN - 1)
                // _SLEEP_STEP_MIN * _SLEEP_STEP_MIN)
            self._sleep_last_turn = 0.0
        elif item == "Touch calibration":
            self._goto("CALIB")
            self._calib_stage = 0
            self._calib_first = None
        elif item == "Touch test":
            self._goto("TOUCHTEST")
            self._tt_last = None
        elif item == "Info":
            self._goto("INFO")
            self._spawn("Reading status", self._gather_info)

    def _start_scan(self) -> None:
        self._spawn("Scanning WiFi", wifi.scan)

    def _load_speakers(self):
        """Discovered speakers annotated with (is_main, grouped).
        Grouped slaves vanish from SSDP, so the master's slave list is
        merged in — otherwise a grouped speaker could never be shown
        (or ungrouped) again."""
        speakers = list(discovery.discover())
        main_ip = str(config.get("wiim_ip") or "")
        slaves: list[tuple[str, str]] = []
        if main_ip:
            try:
                slaves = LinkPlay(main_ip).get_slaves()
            except Exception:
                pass
        slave_ips = {ip for _name, ip in slaves}
        seen = {sp.ip for sp in speakers}
        for name, ip in slaves:
            if ip not in seen:
                speakers.append(discovery.Speaker(name=name, ip=ip))
        return [(sp, sp.ip == main_ip, sp.ip in slave_ips)
                for sp in speakers]

    def _pick_speaker(self) -> None:
        with self._lock:
            if not (0 <= self._cursor < len(self._items)):
                return
            sp, is_main, _grouped = self._items[self._cursor]
        if is_main and config.get("output") != "bt":
            self._flash(f"{sp.name} is already the speaker")
            return
        config.set("wiim_ip", sp.ip)
        config.set("wiim_name", sp.name)
        config.set("output", "wiim")
        if self._worker is not None:
            self._worker.set_wiim(sp.ip)
        self._flash(f"Speaker: {sp.name}")
        self._goto("MENU")

    def _load_bt(self):
        """(device, is_output) rows for the BT speaker screen."""
        from radiowall import btaudio
        current = (str(config.get("bt_mac") or "").upper()
                   if config.get("output") == "bt" else "")
        return [(d, d.mac == current) for d in btaudio.scan()]

    def _pick_bt(self) -> None:
        with self._lock:
            if not (0 <= self._cursor < len(self._items)):
                return
            dev, _is_out = self._items[self._cursor]

        def task():
            from radiowall import btaudio
            ok, msg = btaudio.connect(dev.mac)
            if ok:
                config.set("bt_mac", dev.mac)
                config.set("bt_name", dev.name)
                config.set("output", "bt")
                set_bt = getattr(self._worker, "set_bt", None)
                if set_bt is not None:
                    set_bt(dev.mac, dev.name)
                self._maybe_switch_linkplay_input(dev.name)
                self._flash(f"BT speaker: {dev.name}")
            else:
                self._flash(f"Connect failed: {msg[:24]}")
            return self._load_bt()

        self._spawn(f"Pairing {dev.name}", task)

    @staticmethod
    def _maybe_switch_linkplay_input(bt_name: str) -> None:
        """If the chosen BT device is actually a LinkPlay speaker (like
        a WiiM used as a BT sink), flip its input to Bluetooth — WiiM
        firmware keeps listening to WiFi otherwise and stays silent.
        Best-effort: generic BT speakers are unaffected."""
        try:
            for sp in discovery.discover(timeout_s=2.0):
                if sp.name.strip().lower() == bt_name.strip().lower():
                    lp = LinkPlay(sp.ip)
                    lp.switch_mode("bluetooth")
                    # its device volume becomes a hidden second stage
                    # behind the knob (which drives the A2DP link) — a
                    # low setting makes the whole chain near-silent
                    vol = lp.get_volume()
                    if vol is not None and vol < 40:
                        lp.set_volume(45)
                        log.info("raised %s volume %d -> 45 (BT sink "
                                 "baseline)", sp.name, vol)
                    log.info("switched LinkPlay %s (%s) input to bluetooth",
                             sp.name, sp.ip)
                    return
        except Exception as e:
            log.debug("linkplay input switch skipped: %s", e)

    def _forget_bt(self) -> None:
        with self._lock:
            if not (0 <= self._cursor < len(self._items)):
                return
            dev, is_out = self._items[self._cursor]

        def task():
            from radiowall import btaudio
            btaudio.forget(dev.mac)
            if is_out:                     # forgot the active output
                config.set("output", "wiim")
            self._flash(f"Forgot {dev.name}")
            return self._load_bt()

        self._spawn("Removing", task)

    def _toggle_group(self) -> None:
        """2x on a speaker row: join it to / remove it from the main
        speaker's multiroom group."""
        with self._lock:
            if not (0 <= self._cursor < len(self._items)):
                return
            sp, is_main, grouped = self._items[self._cursor]
        main_ip = str(config.get("wiim_ip") or "")
        if not main_ip:
            self._flash("Pick a main speaker first")
            return
        if is_main:
            self._flash("That IS the main speaker")
            return

        def task():
            if grouped:
                ok = LinkPlay(main_ip).kick_slave(sp.ip)
                self._flash(f"{sp.name} removed" if ok else "Failed")
            else:
                # join goes to the SLAVE, pointing it at the master
                ok = LinkPlay(sp.ip).join_master(main_ip)
                self._flash(f"+ {sp.name} grouped" if ok else "Failed")
            items = self._load_speakers()
            # a just-kicked speaker may not re-announce on SSDP for a
            # while — keep it on screen instead of letting it vanish
            if all(x[0].ip != sp.ip for x in items):
                items.append((sp, False, False))
            return items

        self._spawn("Updating group", task)

    def _pick_network(self) -> None:
        with self._lock:
            if not (0 <= self._cursor < len(self._items)):
                return
            net = self._items[self._cursor]
        if net.known or not net.secured:
            self._spawn(f"Joining {net.ssid}",
                        lambda: [wifi.connect(net.ssid, None)])
            self._screen = "WIFI_RESULT"
        else:
            self._pw_ssid = net.ssid
            self._pw_text = ""
            self._pw_pos = len(_PW_CONTROLS)
            self._goto("PASSWORD")

    def _play_entry(self) -> None:
        with self._lock:
            if not (0 <= self._cursor < len(self._items)):
                return
            entry = self._items[self._cursor]
        play = getattr(self._worker, "play_history", None)
        if play is not None:
            play(entry)
        self.close()                       # drop to the status screen

    def _toggle_star(self) -> None:
        with self._lock:
            if not (0 <= self._cursor < len(self._items)):
                return
            entry = self._items[self._cursor]
        starred = history.toggle_favorite(entry.station_id)
        self._flash(("★ " if starred else "unstarred ") + entry.station_title)
        with self._lock:
            self._items = history.entries(
                favorites_only=self._screen == "FAVORITES")
            self._cursor = min(self._cursor, max(0, len(self._items) - 1))

    def _pick_sleep(self) -> None:
        minutes = self._sleep_min
        set_timer = getattr(self._worker, "set_sleep_timer", None)
        if set_timer is not None:
            set_timer(minutes)
        self._flash("Sleep timer off" if minutes == 0
                    else f"Sleep in {self._fmt_min(minutes)}")
        self._goto("MENU")

    @staticmethod
    def _fmt_min(minutes: int) -> str:
        if minutes >= 60:
            h, m = divmod(minutes, 60)
            return f"{h}h {m:02d}m" if m else f"{h}h"
        return f"{minutes} min"

    def _pw_key(self) -> None:
        key = _PW_STRIP[self._pw_pos]
        if key == "[OK]":
            ssid, pw = self._pw_ssid, self._pw_text
            self._goto("WIFI_RESULT")
            self._spawn(f"Joining {ssid}",
                        lambda: [wifi.connect(ssid, pw)])
        else:
            self._pw_text += key

    def _gather_info(self) -> list[str]:
        ssid, ip = wifi.status()
        wiim = config.get("wiim_name") or "-"
        wiim_ip = config.get("wiim_ip") or "not set"
        return [
            f"WiFi: {ssid or 'not connected'}",
            f"IP: {ip or '-'}",
            f"Speaker: {wiim} ({wiim_ip})",
        ]

    # ---------- drawing ----------------------------------------------------

    def draw(self, device, frame: int, fs: fonts.FontSet) -> None:
        # the menu overlays a playing radio and steals the volume knob —
        # never let it sit open forgotten
        if time.monotonic() - self._last_input > _IDLE_CLOSE_S:
            self.close()
            return
        with canvas(device) as d:
            title = {
                "MENU": "MENU",
                "SETUP_MENU": "SETUP",
                "HISTORY": "HISTORY",
                "FAVORITES": "FAVORITES",
                "SPEAKER": "SPEAKER · WIFI",
                "BTSPEAKER": "SPEAKER · BT",
                "WIFI": "WIFI",
                "WIFI_RESULT": "WIFI",
                "SLEEP": "SLEEP TIMER",
                "PASSWORD": self._pw_ssid[:20],
                "CALIB": "CALIBRATE",
                "TOUCHTEST": "TOUCH TEST",
                "INFO": "INFO",
            }.get(self._screen, "MENU")
            self._draw_titlebar(d, device, fs, title, frame)

            if self._screen == "MENU":
                self._draw_list(d, device, fs, _MENU_ITEMS, self._cursor)
            elif self._screen == "SETUP_MENU":
                self._draw_list(d, device, fs, _SETUP_ITEMS, self._cursor)
            elif self._screen in ("HISTORY", "FAVORITES"):
                with self._lock:
                    rows = [
                        f"{'★ ' if e.favorite else ''}{e.station_title}"
                        f" — {e.place_name}"
                        for e in self._items
                    ]
                if rows:
                    self._draw_list(d, device, fs, rows, self._cursor)
                elif self._screen == "HISTORY":
                    self._draw_center(d, device, fs, "Nothing played yet",
                                      "stations appear after 30s of listening")
                else:
                    self._draw_center(d, device, fs, "No favorites yet",
                                      "2x-press in History (or while playing)")
            elif self._screen == "SPEAKER":
                with self._lock:
                    rows = [
                        f"{'●' if main else '+' if grouped else ' '} "
                        f"{sp.name}  {sp.ip}"
                        for sp, main, grouped in self._items
                    ]
                self._draw_list(d, device, fs, rows, self._cursor,
                                empty="No speakers found")
            elif self._screen == "BTSPEAKER":
                with self._lock:
                    rows = [
                        f"{'●' if is_out else '+' if dev.paired else ' '} "
                        f"{dev.name}"
                        for dev, is_out in self._items
                    ]
                self._draw_list(d, device, fs, rows, self._cursor,
                                empty="No devices found")
            elif self._screen == "WIFI":
                with self._lock:
                    rows = [
                        f"{'*' if n.known else ' '}{n.ssid}"
                        f"  {'' if n.secured else '(open) '}{n.signal}%"
                        for n in self._items
                    ]
                self._draw_list(d, device, fs, rows, self._cursor,
                                empty="No networks found")
            elif self._screen == "SLEEP":
                self._draw_sleep_dial(d, device, fs)
            elif self._screen == "WIFI_RESULT":
                with self._lock:
                    result = self._items[0] if self._items else None
                if result is not None:
                    ok, detail = result
                    self._draw_center(d, device, fs,
                                      "Connected" if ok else "Failed",
                                      detail[:40])
            elif self._screen == "PASSWORD":
                self._draw_password(d, device, fs)
            elif self._screen == "CALIB":
                self._draw_calib(d, device, fs, frame)
            elif self._screen == "TOUCHTEST":
                self._draw_touch_test(d, device, fs)
            elif self._screen == "INFO":
                with self._lock:
                    rows = list(self._items)
                self._draw_list(d, device, fs, rows, cursor=-1)

            self._draw_overlays(d, device, fs, frame)

    def _draw_titlebar(self, d, device, fs, title: str, frame: int) -> None:
        W = device.width
        hint = {
            "MENU": "turn·pick  press·ok  hold·close",
            "PASSWORD": "press·type  2x·del  hold·back",
            "SLEEP": "turn·time  press·set  hold·back",
            "HISTORY": "press·play  2x·star  hold·back",
            "FAVORITES": "press·play  2x·unstar  hold·back",
            "SPEAKER": "press·main  2x·group  hold·back",
            "TOUCHTEST": "tap·test  hold·back",
            "BTSPEAKER": "press·use  2x·forget  hold·back",
        }.get(self._screen, "hold·back")
        hw = d.textlength(hint, font=fs.tiny)
        d.text((W - hw - 2, 0), hint, font=fs.tiny, fill=AMBER_GHOST)
        avail = W - hw - 10                # title must not run into the hint
        while title and d.textlength(title, font=fs.tiny) > avail:
            title = title[:-2].rstrip() + "…"
        d.text((2, 0), title, font=fs.tiny, fill=AMBER_DIM)
        d.line((0, 11, W, 11), fill=AMBER_GHOST)

    def _draw_list(self, d, device, fs, rows: list[str], cursor: int,
                   empty: str = "") -> None:
        W, H = device.width, device.height
        if self._busy_text():
            return
        if not rows:
            if empty:
                self._draw_center(d, device, fs, empty, "")
            return
        # row height from real font metrics: the old fixed 13px grid was
        # shorter than the 15px (ascent+descent) text, so descenders
        # stuck out under the highlight and the next row's highlight
        # painted over them
        try:
            asc, desc = fs.small.getmetrics()
        except AttributeError:
            asc, desc = 10, 2
        text_h = asc + desc
        row_h = text_h + 1
        top = 14
        visible = max(1, (H - top) // row_h)
        first = max(0, min(cursor - visible // 2,
                           len(rows) - visible)) if cursor >= 0 else 0
        y = top
        for i in range(first, min(first + visible, len(rows))):
            selected = i == cursor
            if selected:
                d.rectangle((0, y - 1, W, y + text_h), fill=AMBER_GHOST)
                d.text((2, y), "▸", font=fs.small, fill=AMBER_BRIGHT)
            text = rows[i]
            avail = W - 16
            font = fs.pick_small(text)
            while text and d.textlength(text, font=font) > avail:
                text = text[:-2].rstrip() + "…"
            d.text((13, y), text, font=font,
                   fill=AMBER_BRIGHT if selected else AMBER)
            y += row_h
        if len(rows) > visible:                    # scroll indicator
            frac0 = first / len(rows)
            frac1 = (first + visible) / len(rows)
            d.rectangle((W - 2, top + int(frac0 * (H - top)),
                         W - 1, top + int(frac1 * (H - top))), fill=AMBER_DIM)

    def _draw_password(self, d, device, fs) -> None:
        W, H = device.width, device.height
        if self._busy_text():
            return
        # typed text (tail if too long)
        shown = self._pw_text
        while shown and d.textlength(shown + "_", font=fs.small) > W - 8:
            shown = shown[1:]
        d.text((4, 14), shown + "_", font=fs.small, fill=AMBER)
        # character strip, selection centered; neighbors are laid out by
        # their real rendered width so multi-char keys like [OK] never
        # overlap their neighbors
        y = H - 20
        cx = W // 2
        gap = 9

        def _label(idx: int) -> str:
            key = _PW_STRIP[idx % len(_PW_STRIP)]
            return "␣" if key == " " else key

        sel = _label(self._pw_pos)
        sel_w = d.textlength(sel, font=fs.med)
        d.text((cx - sel_w / 2, y), sel, font=fs.med, fill=AMBER_BRIGHT)
        d.text((cx - 4, y - 5), "▾", font=fs.tiny, fill=AMBER_DIM)

        x = cx + sel_w / 2 + gap                     # rightward neighbors
        off = 1
        while x < W and off < len(_PW_STRIP):
            label = _label(self._pw_pos + off)
            d.text((x, y + 3), label, font=fs.small, fill=AMBER_GHOST)
            x += d.textlength(label, font=fs.small) + gap
            off += 1
        x = cx - sel_w / 2 - gap                     # leftward neighbors
        off = 1
        while x > 0 and off < len(_PW_STRIP):
            label = _label(self._pw_pos - off)
            w = d.textlength(label, font=fs.small)
            d.text((x - w, y + 3), label, font=fs.small, fill=AMBER_GHOST)
            x -= w + gap
            off += 1

    def _draw_sleep_dial(self, d, device, fs) -> None:
        W, H = device.width, device.height
        big = "Off" if self._sleep_min == 0 else self._fmt_min(self._sleep_min)
        w = d.textlength(big, font=fs.big)
        d.text(((W - w) // 2, 16), big, font=fs.big,
               fill=AMBER_BRIGHT if self._sleep_min else AMBER_DIM)
        if self._sleep_min:
            ends = time.strftime(
                "%H:%M", time.localtime(time.time() + self._sleep_min * 60))
            sub = f"music off at {ends}"
        else:
            sub = "turn to set a timer"
        sw = d.textlength(sub, font=fs.tiny)
        d.text(((W - sw) // 2, H - 13), sub, font=fs.tiny, fill=AMBER_DIM)

    def _tt_tap(self, x: float, y: float) -> None:
        """Resolve a tap exactly like a play-tap would — same saved
        calibration, same nearest-city lookup — but silently."""
        import math

        from radiowall.places_db import country_name

        cal = geo.load_calibration()
        lat, lon = geo.tap_to_latlon(x, y, cal)
        name, country, dist = "(no places db)", "", 0.0
        if self._places is not None:
            place = self._places.find_nearest(lat, lon)
            if place is not None:
                name = place.name
                country = country_name(place.country)
                dlat = (place.lat - lat) * 111.0
                dlon = ((place.lon - lon) * 111.0
                        * math.cos(math.radians(lat)))
                dist = (dlat * dlat + dlon * dlon) ** 0.5
        self._tt_last = (x, y, lat, lon, name, country, dist)
        log.info("touch test: (%.3f, %.3f) -> (%.2f, %.2f) -> %s, %s "
                 "(%.0f km)", x, y, lat, lon, name, country, dist)

    def _draw_touch_test(self, d, device, fs) -> None:
        W, H = device.width, device.height
        if self._tt_last is None:
            self._draw_center(d, device, fs, "Tap the map",
                              "shows the resolved city — plays nothing")
            return
        x, y, lat, lon, name, country, dist = self._tt_last
        line1 = f"{name} · {country}" if country else name
        w1 = d.textlength(line1, font=fs.pick_small(line1))
        d.text(((W - int(w1)) // 2, 16), line1,
               font=fs.pick_small(line1), fill=AMBER_BRIGHT)
        line2 = f"lat {lat:+.2f}  lon {lon:+.2f}  ·  {dist:.0f} km to city"
        w2 = d.textlength(line2, font=fs.tiny)
        d.text(((W - int(w2)) // 2, 34), line2, font=fs.tiny, fill=AMBER)
        line3 = f"raw x {x:.3f}  y {y:.3f}"
        w3 = d.textlength(line3, font=fs.tiny)
        d.text(((W - int(w3)) // 2, 48), line3, font=fs.tiny, fill=AMBER_DIM)

    def _draw_calib(self, d, device, fs, frame: int) -> None:
        if self._calib_stage == 0:
            line1, line2 = "Tap the TOP-LEFT", "corner of the map"
        elif self._calib_stage == 1:
            line1, line2 = "Tap the BOTTOM-RIGHT", "corner of the map"
        else:
            line1, line2 = "Done", "hold knob to go back"
        if (frame // 25) % 2 == 0 or self._calib_stage == 2:
            self._draw_center(d, device, fs, line1, line2)

    def _draw_center(self, d, device, fs, line1: str, line2: str) -> None:
        W, H = device.width, device.height
        w1 = d.textlength(line1, font=fs.small)
        d.text(((W - w1) // 2, int(H * 0.32)), line1, font=fs.small,
               fill=AMBER)
        if line2:
            w2 = d.textlength(line2, font=fs.tiny)
            d.text(((W - w2) // 2, int(H * 0.62)), line2, font=fs.tiny,
                   fill=AMBER_DIM)

    def _busy_text(self) -> str | None:
        with self._lock:
            return self._busy

    def _draw_overlays(self, d, device, fs, frame: int) -> None:
        W, H = device.width, device.height
        busy = self._busy_text()
        if busy:
            dots = "." * (1 + (frame // 12) % 3)
            text = busy + dots
            tw = d.textlength(text, font=fs.small)
            d.text(((W - tw) // 2, int(H * 0.45)), text, font=fs.small,
                   fill=AMBER)
        if self._notice and time.monotonic() < self._notice_until:
            try:
                t_asc, t_desc = fs.tiny.getmetrics()
            except AttributeError:
                t_asc, t_desc = 8, 2
            toast_h = t_asc + t_desc + 2
            tw = d.textlength(self._notice, font=fs.tiny)
            d.rectangle((0, H - toast_h, W, H), fill=(0, 0, 0))
            d.text(((W - tw) // 2, H - toast_h + 1), self._notice,
                   font=fs.tiny, fill=AMBER_BRIGHT)
