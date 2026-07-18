"""Radio worker: owns all network I/O, driven by a command queue.

The render loop must never block, so every radio.garden/LinkPlay call
happens on this thread. Commands are tiny dataclasses; the queue is
coalesced on drain:

- a newer PlayAt supersedes queued PlayAt/Next commands
- Stop discards everything queued before it
- SetVolume values collapse to the newest, sent to the WiiM only after
  200 ms of quiet (the ESP32 debounce, relocated here)

After a successful play the worker points the visualizer's decoder at
the same resolved stream URL (its own independent ffmpeg connection).

Headless vertical slice:
    python -m radiowall.radio 48.21 16.37
    → plays the nearest city's first station on the WiiM;
      stdin: n = next, v <0-100> = volume, q = stop & quit
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass

from radiowall.audio import decoder
from radiowall.linkplay import LinkPlay
from radiowall.places_db import PlacesDB, country_name
from radiowall.radio_garden import RadioGarden
from radiowall.state import AppState, Session

log = logging.getLogger(__name__)

VOL_DEBOUNCE_S = 0.2

# Visualizer sync polling: after a play command, poll the WiiM's curpos
# often (it locks the visualizer to the speaker as soon as sound starts),
# then back off to an occasional drift check.
SYNC_FAST_S = 2.0
SYNC_SLOW_S = 10.0
SYNC_FAST_WINDOW_S = 30.0


# --- commands ------------------------------------------------------------

@dataclass(frozen=True)
class PlayAt:
    lat: float
    lon: float


@dataclass(frozen=True)
class Next:
    pass


@dataclass(frozen=True)
class Stop:
    pass


@dataclass(frozen=True)
class SetVolume:
    volume: int


@dataclass(frozen=True)
class SetSleep:
    minutes: int          # 0 = cancel


Command = PlayAt | Next | Stop | SetVolume | SetSleep


def wiim_ip() -> str:
    """Speaker address: env override > config store (set by the on-device
    setup UI) > empty. Empty means 'not configured yet' — the worker
    then tells the user to run setup instead of poking a dead IP."""
    env = os.getenv("RADIOWALL_WIIM_IP", "").strip()
    if env:
        return env
    from radiowall import config
    return str(config.get("wiim_ip") or "").strip()


class RadioWorker:
    def __init__(self, state: AppState, places: PlacesDB,
                 rg: RadioGarden | None = None,
                 wiim: LinkPlay | None = None,
                 use_decoder: bool = True) -> None:
        self._state = state
        self._places = places
        self._rg = rg or RadioGarden()
        if wiim is not None:
            self._wiim: LinkPlay | None = wiim
        else:
            ip = wiim_ip()
            self._wiim = LinkPlay(ip) if ip else None
            if not ip:
                log.warning("no WiiM configured — hold the knob for setup")
        self._use_decoder = use_decoder
        self._queue: queue.Queue[Command] = queue.Queue()
        self._session: Session | None = None
        self._running = False
        self._pending_volume: int | None = None
        self._volume_deadline = 0.0
        self._sent_volume: int | None = None
        self._played_at = 0.0            # monotonic time of last play cmd
        self._sync_logged = False        # one "synced" log line per station
        self._sleep_deadline: float | None = None
        self._sync_fast_s = SYNC_FAST_S  # instance attrs so tests can shrink
        self._sync_slow_s = SYNC_SLOW_S
        self._thread = threading.Thread(target=self._loop, name="radio",
                                        daemon=True)
        self._sync_thread = threading.Thread(
            target=self._sync_loop, name="vis-sync", daemon=True)

    # --- public API (any thread) ----------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread.start()
        if self._use_decoder:
            self._sync_thread.start()

    def stop(self, stop_playback: bool = False) -> None:
        """Shut the worker down. With stop_playback=True (natural program
        exit) the WiiM is silenced too — a stopped RadioWall should not
        leave the radio playing forever."""
        self._running = False
        self._queue.put(Stop())          # wake the loop
        self._thread.join(timeout=2)
        if stop_playback and self._session is not None:
            if self._use_decoder:
                decoder.stop()
            if self._wiim is not None:
                self._wiim.stop()
            log.info("playback stopped on exit")

    def submit(self, cmd: Command) -> None:
        self._queue.put(cmd)

    def set_sleep_timer(self, minutes: int) -> None:
        """Arm (or cancel with 0) the sleep timer — setup-UI entry point."""
        self.submit(SetSleep(minutes))

    def sleep_minutes_left(self) -> int:
        """Minutes until the armed sleep timer fires (0 = not armed)."""
        deadline = self._sleep_deadline
        if deadline is None:
            return 0
        left = deadline - time.monotonic()
        return int(left // 60) + 1 if left > 0 else 0

    def set_wiim(self, ip: str) -> None:
        """Swap the speaker (called by the setup UI after discovery).
        Just an attribute swap — no network here, this runs on the
        render thread."""
        self._wiim = LinkPlay(ip)
        self._sent_volume = None
        log.info("speaker set to %s", ip)

    # --- worker thread ----------------------------------------------------

    def _loop(self) -> None:
        self._sync_volume()
        while self._running:
            try:
                cmd = self._queue.get(timeout=0.05)
            except queue.Empty:
                self._flush_volume()
                self._check_sleep()
                continue
            if not self._running:
                break
            cmd = self._coalesce(cmd)
            if isinstance(cmd, PlayAt):
                self._handle_play_at(cmd.lat, cmd.lon)
            elif isinstance(cmd, Next):
                self._handle_next()
            elif isinstance(cmd, Stop):
                self._handle_stop()
            elif isinstance(cmd, SetSleep):
                self._handle_sleep(cmd.minutes)
            self._flush_volume()
            self._check_sleep()

    def _sync_loop(self) -> None:
        """Poll the WiiM's playback position and hand it to the decoder,
        which anchors the visualizer's consumption clock to what the
        speaker is actually playing (replaces guessing VIS_DELAY). Own
        thread: getPlayerStatus can block for seconds and must never
        stall touch handling on the worker thread."""
        last_poll = 0.0
        while self._running:
            time.sleep(min(0.25, self._sync_fast_s / 4))
            now = time.monotonic()
            if self._session is None:
                continue
            # looked up per-iteration: the setup UI can swap the speaker
            # at runtime, and fakes/tests may not have the method at all
            get_position = getattr(self._wiim, "get_position", None)
            if get_position is None:
                continue
            fast = now - self._played_at < SYNC_FAST_WINDOW_S
            interval = self._sync_fast_s if fast else self._sync_slow_s
            # a fresh play command restarts the cadence immediately
            if now - max(last_poll, self._played_at) < interval:
                continue
            last_poll = now
            t0 = now
            result = get_position()
            if result is None:
                continue
            status, pos_s = result
            # curpos stays 0 while the WiiM is still buffering; syncing
            # then would freeze the visualizer on the burst start.
            if status != "play" or pos_s <= 0:
                continue
            # position was true somewhere inside the HTTP round trip
            measured_at = (t0 + time.monotonic()) / 2
            decoder.sync_playback(pos_s, measured_at)
            if not self._sync_logged:
                self._sync_logged = True
                log.info("visualizer synced to WiiM position %.1fs", pos_s)

    def _absorb_volume(self, cmd: SetVolume) -> None:
        self._pending_volume = cmd.volume
        self._volume_deadline = time.monotonic() + VOL_DEBOUNCE_S

    def _coalesce(self, cmd: Command) -> Command | None:
        """Compact a burst without breaking command order:

        - SetVolume never blocks the queue — absorbed into the debouncer
        - a newer PlayAt or Stop supersedes whatever we were about to do
          (retarget while loading / panic stop)
        - a queued Next after a PlayAt stays queued and runs afterwards

        Returns None when everything absorbed was volume-only.
        """
        if isinstance(cmd, SetVolume):
            self._absorb_volume(cmd)
            cmd = None
        while True:
            try:
                nxt = self._queue.queue[0]          # peek
            except IndexError:
                return cmd
            if isinstance(nxt, SetVolume):
                self._absorb_volume(self._queue.get_nowait())
            elif isinstance(nxt, (PlayAt, Stop)) or cmd is None:
                cmd = self._queue.get_nowait()      # supersede / take first
            else:
                return cmd                          # Next waits its turn

    def _flush_volume(self) -> None:
        if (self._pending_volume is not None
                and time.monotonic() >= self._volume_deadline):
            vol = self._pending_volume
            if self._wiim is None:
                self._pending_volume = None
                return
            if vol != self._sent_volume:
                if self._wiim.set_volume(vol):
                    self._sent_volume = vol
                else:
                    log.warning("volume set failed")
            self._pending_volume = None

    def _sync_volume(self) -> None:
        if self._wiim is None:
            return
        vol = self._wiim.get_volume()
        if vol is not None:
            self._sent_volume = vol
            self._state.set_volume(vol)
            log.info("WiiM volume: %d", vol)

    # --- handlers -------------------------------------------------------

    def _handle_play_at(self, lat: float, lon: float) -> None:
        place = self._places.find_nearest(lat, lon)
        if place is None:
            self._state.set_status("No places database")
            return
        log.info("touch (%.2f, %.2f) -> %s, %s", lat, lon,
                 place.name, place.country)
        self._state.set_loading(place.name, country_name(place.country))
        stations = self._rg.get_stations(place.id)
        if not stations:
            self._state.set_status("No stations found")
            self._to_idle_or_playing()
            return
        self._session = Session(origin_lat=lat, origin_lon=lon,
                                place=place, stations=stations)
        self._play_next_in_session()

    def _handle_next(self) -> None:
        if self._session is None:
            self._state.set_status("Nothing playing")
            return
        if self._session.exhausted and not self._hop_city():
            return
        self._play_next_in_session()

    def _hop_city(self) -> bool:
        s = self._session
        if not s.can_hop:
            self._state.set_status("No more stations")
            return False
        place = self._places.find_nearest_excluding(
            s.origin_lat, s.origin_lon, s.visited)
        if place is None:
            self._state.set_status("No more stations")
            return False
        log.info("city hop -> %s, %s (%d visited)",
                 place.name, place.country, len(s.visited))
        self._state.set_loading(place.name, country_name(place.country))
        stations = self._rg.get_stations(place.id)
        if not stations:
            # Mark visited WITHOUT entering: the previous station is still
            # audibly playing and its info must survive on screen. The next
            # NEXT skips this city via the visited set.
            s.visited.add(place.id)
            self._to_idle_or_playing()      # un-stick the "Tuning..." phase
            self._state.set_status("No stations found")   # after: set_playing clears status
            return False
        s.enter_city(place, stations)
        return True

    def _play_next_in_session(self) -> None:
        s = self._session
        if s.exhausted:
            self._state.set_status("No more stations")
            return
        station = s.advance()
        if self._wiim is None:
            self._state.set_status("No speaker — hold knob for setup")
            self._state.set_idle()
            return
        self._state.set_loading(s.place.name, country_name(s.place.country))
        stream_url = self._rg.resolve_stream_url(station.id)
        if not stream_url:
            self._state.set_status("Failed to play")
            self._to_idle_or_playing()
            return
        if not self._wiim.play(stream_url):
            self._state.set_status("Failed to play")
            self._to_idle_or_playing()
            return
        self._state.set_playing(s.place.name, country_name(s.place.country),
                                station.title,
                                s.playing_index + 1, len(s.stations))
        log.info("playing %d/%d: %s (%s)", s.playing_index + 1,
                 len(s.stations), station.title, s.place.name)
        if self._use_decoder:
            decoder.stop()
            decoder.start(stream_url)
        self._played_at = time.monotonic()
        self._sync_logged = False

    def _handle_sleep(self, minutes: int) -> None:
        """Arm/cancel the sleep timer. Belt and braces: the WiiM gets its
        native setSleepTimer too (a few seconds later than ours, so we
        normally stop it first), so the music dies on time even if this
        board hangs. The timer survives station changes and manual stops
        by design — 'off in 60 min' means off in 60, whatever you tune
        to meanwhile. Only 'Off' disarms it."""
        native = getattr(self._wiim, "set_sleep_timer", None)
        if minutes <= 0:
            self._sleep_deadline = None
            self._state.set_sleep(None)
            if native:
                native(0)
            self._state.set_status("Sleep timer off")
            log.info("sleep timer cancelled")
        else:
            self._sleep_deadline = time.monotonic() + minutes * 60
            self._state.set_sleep(self._sleep_deadline)
            if native:
                native(minutes * 60 + 10)
            self._state.set_status(f"Sleep in {minutes} min")
            log.info("sleep timer armed: %d min", minutes)

    def _check_sleep(self) -> None:
        if (self._sleep_deadline is not None
                and time.monotonic() >= self._sleep_deadline):
            log.info("sleep timer expired — stopping")
            self._sleep_deadline = None
            self._state.set_sleep(None)
            self._handle_stop()
            self._state.set_status("Good night", ttl_s=10.0)

    def _handle_stop(self) -> None:
        if self._use_decoder:
            decoder.stop()
        if self._wiim is not None:
            self._wiim.stop()
        self._session = None
        self._state.set_idle()
        log.info("stopped")

    def _to_idle_or_playing(self) -> None:
        """After a failure, fall back to reflecting what's actually true."""
        s = self._session
        station = s.current_station() if s else None
        if s and station:
            self._state.set_playing(s.place.name, country_name(s.place.country),
                                    station.title, s.playing_index + 1,
                                    len(s.stations))
        else:
            self._state.set_idle()


def _main() -> int:
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    if len(sys.argv) != 3:
        print("usage: python -m radiowall.radio <lat> <lon>")
        return 2

    from radiowall import places_db

    state = AppState()
    places = PlacesDB.load(places_db.default_path())
    worker = RadioWorker(state, places, use_decoder=False)
    worker.start()
    worker.submit(PlayAt(float(sys.argv[1]), float(sys.argv[2])))

    print("commands: n = next station, v <0-100> = volume, q = quit")
    try:
        for line in sys.stdin:
            line = line.strip()
            if line == "n":
                worker.submit(Next())
            elif line.startswith("v "):
                worker.submit(SetVolume(int(line[2:])))
            elif line == "q":
                break
            snap = state.snapshot()
            print(f"  [{snap.phase.value}] {snap.place_name} — "
                  f"{snap.station_title} ({snap.station_index}/"
                  f"{snap.station_total}) vol={snap.volume}")
    except KeyboardInterrupt:
        pass
    finally:
        worker.submit(Stop())
        time.sleep(0.5)
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
