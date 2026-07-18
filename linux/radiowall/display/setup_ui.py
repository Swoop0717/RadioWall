"""On-device setup UI — everything configurable without a phone.

Entered by holding the encoder ≥3 s (Gesture.VERY_LONG). One knob
drives everything: rotate = move / pick character, short press =
select, long press = back (at the root: exit).

Screens:
  MENU     Speaker · WiFi · Touch calibration · Info · Exit
  SPEAKER  SSDP-discover LinkPlay devices, pick one → config['wiim_ip']
  WIFI     nmcli scan, pick an SSID (known ones connect directly)
  PASSWORD rotary character entry for WiFi passwords
  CALIB    tap top-left then bottom-right map corner → config['touch_calib']
  INFO     SSID, IP, configured speaker

All network work (discovery, scan, connect) runs on daemon threads;
the UI thread only reads the result slots. A generation counter makes
stale thread results harmless (user backed out and reopened).

The class is UI-state only — display drawing happens in draw(), input
in handle_*(); both are called from the main loop. No hardware
dependencies, so the whole flow is unit-testable and emulator-friendly.
"""

from __future__ import annotations

import logging
import threading
import time

from luma.core.render import canvas

from radiowall import config, discovery, wifi
from radiowall.display import fonts

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

_MENU_ITEMS = ["Speaker", "WiFi", "Sleep timer", "Touch calibration",
               "Info", "Exit"]

# Sleep dial: oven-timer feel. Slow turning steps 10 min per detent;
# once detents arrive faster than _SLEEP_FAST_S apart the step grows to
# 30 min, so 3 h is one confident spin, not 18 clicks.
_SLEEP_STEP_MIN = 10
_SLEEP_STEP_FAST_MIN = 30
_SLEEP_FAST_S = 0.08
_SLEEP_MAX_MIN = 720


class SetupUI:
    def __init__(self, worker=None) -> None:
        self._worker = worker
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
        self._sleep_min = 0
        self._sleep_last_turn = 0.0

    # ---------- lifecycle ------------------------------------------------

    def open(self) -> None:
        self.active = True
        self._goto("MENU")
        log.info("setup opened")

    def close(self) -> None:
        self.active = False
        self._gen += 1
        log.info("setup closed")

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
        if self._busy:
            return
        if self._screen == "MENU":
            self._menu_select(_MENU_ITEMS[self._cursor])
        elif self._screen == "SPEAKER":
            self._pick_speaker()
        elif self._screen == "WIFI":
            self._pick_network()
        elif self._screen == "PASSWORD":
            self._pw_key()
        elif self._screen == "SLEEP":
            self._pick_sleep()
        elif self._screen in ("INFO", "WIFI_RESULT"):
            self._goto("MENU")

    def handle_long(self) -> None:
        """Back one level; at the root, exit setup."""
        if self._screen == "MENU":
            self.close()
        elif self._screen == "PASSWORD":
            self._goto("WIFI")
            self._start_scan()
        else:
            self._goto("MENU")

    def handle_double(self) -> None:
        if self._screen == "PASSWORD":     # backspace shortcut
            self._pw_text = self._pw_text[:-1]

    def handle_tap(self, x: float, y: float) -> None:
        """Touch input while setup is open — used by calibration."""
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
        with self._lock:
            return len(self._items)

    def _menu_select(self, item: str) -> None:
        if item == "Speaker":
            self._goto("SPEAKER")
            self._spawn("Searching speakers", discovery.discover)
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
        elif item == "Info":
            self._goto("INFO")
            self._spawn("Reading status", self._gather_info)
        elif item == "Exit":
            self.close()

    def _start_scan(self) -> None:
        self._spawn("Scanning WiFi", wifi.scan)

    def _pick_speaker(self) -> None:
        with self._lock:
            if not (0 <= self._cursor < len(self._items)):
                return
            sp = self._items[self._cursor]
        config.set("wiim_ip", sp.ip)
        config.set("wiim_name", sp.name)
        if self._worker is not None:
            self._worker.set_wiim(sp.ip)
        self._flash(f"Speaker: {sp.name}")
        self._goto("MENU")

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
        with canvas(device) as d:
            title = {
                "MENU": "SETUP",
                "SPEAKER": "SPEAKER",
                "WIFI": "WIFI",
                "WIFI_RESULT": "WIFI",
                "SLEEP": "SLEEP TIMER",
                "PASSWORD": self._pw_ssid[:20],
                "CALIB": "CALIBRATE",
                "INFO": "INFO",
            }.get(self._screen, "SETUP")
            self._draw_titlebar(d, device, fs, title, frame)

            if self._screen == "MENU":
                self._draw_list(d, device, fs, _MENU_ITEMS, self._cursor)
            elif self._screen == "SPEAKER":
                with self._lock:
                    rows = [f"{s.name}  {s.ip}" for s in self._items]
                self._draw_list(d, device, fs, rows, self._cursor,
                                empty="No speakers found")
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
            elif self._screen == "INFO":
                with self._lock:
                    rows = list(self._items)
                self._draw_list(d, device, fs, rows, cursor=-1)

            self._draw_overlays(d, device, fs, frame)

    def _draw_titlebar(self, d, device, fs, title: str, frame: int) -> None:
        W = device.width
        hint = {
            "MENU": "turn·pick  press·ok  hold·exit",
            "PASSWORD": "press·type  2x·del  hold·back",
            "SLEEP": "turn·time  press·set  hold·back",
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
        row_h = 13
        visible = max(1, (H - 14) // row_h)
        first = max(0, min(cursor - visible // 2,
                           len(rows) - visible)) if cursor >= 0 else 0
        y = 14
        for i in range(first, min(first + visible, len(rows))):
            selected = i == cursor
            if selected:
                d.rectangle((0, y - 1, W, y + row_h - 2), fill=AMBER_GHOST)
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
            d.rectangle((W - 2, 14 + int(frac0 * (H - 14)),
                         W - 1, 14 + int(frac1 * (H - 14))), fill=AMBER_DIM)

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
            tw = d.textlength(self._notice, font=fs.tiny)
            d.rectangle((0, H - 12, W, H), fill=(0, 0, 0))
            d.text(((W - tw) // 2, H - 11), self._notice, font=fs.tiny,
                   fill=AMBER_BRIGHT)
